# 1 ms 周期循环：从阶段耗时看见积压

10 个周期，每轮固定整数运算，记录 `begin`、`compute_end`、`end`。输出阶段平时请求等待 100 μs，第 3 轮请求等待 3 ms。计划释放按绝对单调时钟推进，超期后不重置。程序不接设备、不设置 RT 优先级，也不构成控制算法或实时性测试。

## 准备与一键运行

Ubuntu 24.04 示例：

```bash
sudo apt-get update
sudo apt-get install build-essential pkg-config \
  lttng-tools liblttng-ust-dev babeltrace2 python3
cd demo
bash run.sh
```

先解压发布包，在发布包根目录执行上面的 `cd demo`。采集阶段使用同一普通用户，不混用 sudo。默认 UST 无需内核模块。工具找不到、开发库缺失或连接会话失败时，脚本会立即退出并显示错误。

`run.sh` 编译源文件、创建唯一会话、启用 64 KiB × 4 的用户态通道与 `control:*`，补 vpid/vtid，先开始采集再运行应用。随后停止采集、显示统计、销毁会话，最后用 Babeltrace 2 解码并运行分析脚本。

输出是脚本打印的 `trace-control-loop-*` 目录、`events-control-loop-*.txt` 和对应 `.summary.json`。反复运行会生成不同名字，不会删除已有 trace。

## 想逐条执行时

在 demo 目录执行。先确认每条命令成功，再继续下一步。

```bash
cc -O2 -Wall -Wextra -Werror -I. demo.c demo-tp.c \
  $(pkg-config --cflags --libs lttng-ust) -ldl -o demo
session="control-manual-$$"
trace_dir="$PWD/trace-$session"
lttng create "$session" --output="$trace_dir"
lttng enable-channel --session="$session" --userspace \
  --subbuf-size=64K --num-subbuf=4 ust
lttng enable-event --session="$session" --userspace \
  --channel=ust 'control:*'
lttng add-context --session="$session" --userspace \
  --channel=ust --type=vpid --type=vtid
lttng start "$session"
./demo
lttng stop "$session"
lttng list "$session"
lttng destroy "$session"
babeltrace2 "$trace_dir" > "$session.txt"
python3 analyze.py "$session.txt"
```

中途退出时，只清理自己创建的会话：`lttng destroy "$session"`。不要用 destroy --all 影响别人的采集。

## 源码与埋点

- `demo.c`：CLOCK_MONOTONIC 绝对时间释放；`mark()` 读取实际时刻并调用 `lttng_ust_tracepoint(control, phase, ...)`。
- `demo-tp.h`：定义 `control:phase`，字段为 cycle、phase、release_ns、stamp_ns。
- `demo-tp.c`：定义探针实现，编译时与应用链接。
- `run.sh`：编译、会话配置、采集、解码与分析。
- `analyze.py`：校验完整性并计算周期和阶段指标。

程序故意保留超期后的原始释放计划，便于看见积压。如何处理真实控制系统中的积压、跳帧或截止时间失败，需要按控制需求另行设计。

## 怎样读结果

先确认 `events=30 complete_cycles=10`，并检查 `lttng list` 的 `Discarded events: 0`。脚本检查每轮三个阶段恰好各出现一次、时间顺序正确、同轮 release 一致、计划释放间隔为 1 ms。

JSON 中的指标全部以 ms 为单位：

- late：begin − release，启动晚了多久。
- compute：compute_end − begin，包含相邻埋点等开销。
- output：end − compute_end，包含模拟输出等待与调度。
- exec：end − begin，实际进入循环到结束。
- response：end − release，从计划释放到完成。
- deadline_missed：response > 1 ms。

第 3 轮 output 应能反映代码插入的等待；后续周期可能 exec 很短、response 却仍很长。具体数值和超期数量随运行环境变化，不应把给出的数字当断言。

`example-events.txt` 是 2026-10-18 实测后替换主机名和线程标识的事件文本；可直接验证分析器：

```bash
python3 analyze.py example-events.txt
```

这会生成 `example-events.summary.json`，与 `example-summary.json` 中的周期指标一致。后者另含环境和验证范围。原始 CTF 留在工作资料，未放入发布包。哈希见 `source-sha256.txt`。

本次验证使用 WSL2 / Ubuntu 24.04、PREEMPT_DYNAMIC、SCHED_OTHER，LTTng-tools 2.13.11、UST 2.13.7、Babeltrace 2.0.5、GCC 13.3。依赖从官方包解压到隔离目录；一键脚本的编译和采集流程已实际执行，常规 apt 安装方式未在同次环境重装测试。

结果：30 条完整记录、10 个周期、0 丢弃，第 3 轮 output=3.109918 ms、response=3.205960 ms，第 4 轮 late=2.213927 ms，总共 3 个超期周期。没有预热，第 1 轮受首次执行开销等影响；这个小例子用于分析流程，性能对比请看发布包 `benchmark/` 的 70 次实验。

用户态事件只证明阶段耗时。进一步区分阻塞、就绪等待与运行，需要内核事件；匹配模块、权限、联合采集命令和 Trace Compass 操作参考见发布包根目录《技术补充.md》。本次未执行内核采集或 PREEMPT_RT 测试。
