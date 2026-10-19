# 用户态与内核调度联合追踪

这个示例用同一个 1 ms 周期循环，在第 3 轮构造两种接近 40 ms 的延迟：

- `blocked`：控制线程等待 eventfd，辅助线程约 40 ms 后写入。
- `ready`：约 20 ms 后写入 eventfd，但辅助线程继续占用同一 CPU 约 20 ms。

控制线程为 SCHED_FIFO / 50，辅助线程为 SCHED_FIFO / 70，默认均绑定 CPU 1。程序运行 10 个周期，只有第 3 轮注入等待。辅助线程的忙等有 20 ms 上限；计划释放时间每轮加 1 ms，超期后不重置。

建议在至少 2 个 vCPU、4 GiB 内存的独立 Linux 实验机运行。该程序故意制造实时优先级竞争，不能当成生产控制代码。

## 环境准备

Ubuntu 24.04：

```bash
sudo apt-get update
sudo apt-get install build-essential pkg-config curl ca-certificates \
  linux-headers-$(uname -r) lttng-tools liblttng-ust-dev \
  babeltrace2 python3-bt2
```

还需要匹配当前内核的 LTTng 模块。已有可工作的发行版模块时，先检查：

```bash
sudo modprobe lttng-tracer
sudo lttng list --kernel
```

确认存在 `sched_switch`、`sched_wakeup`、`sched_wakeup_new`。只安装 UST 不会带来内核事件。

本次 Ubuntu 6.8.0-147-generic 的发行版 DKMS 包在构建 timer 探针时遇到回移补丁的 ABI 冲突，因此实验采用附带的 `build-sched-module.sh`：从官方校验过的 LTTng-modules 2.13.23 归档构建，仅保留 sched 与 statedump 探针。未修改调度事件定义、缓冲区或时间戳实现。

需要复现这套模块构建时，以普通用户运行：

```bash
bash build-sched-module.sh
```

脚本在自己的工作目录下载源码，`make -j1` 避免并行构建的内存峰值，再通过 sudo 安装模块、执行 depmod 并检查事件列表。它仅用于实验环境，不是适用于所有内核版本的通用安装器。

## 编译、采集与分析

在 `joint-demo` 目录运行：

```bash
sudo bash run.sh
```

默认 A/B 各做 3 次。可选参数：`sudo CPU=1 TRIALS=3 bash run.sh`。CPU 必须存在且允许使用；线程优先级或亲和性设置失败会终止，不会悄悄退回普通调度。

脚本同时启用用户态 `control:*` 与三个内核调度事件。采集时不按当前 TID 过滤：唤醒控制线程的事件发生在辅助线程上下文，过滤掉它就无法计算就绪等待。

所有 lttng 控制命令与程序使用同一 root 会话。脚本只销毁自己的唯一会话，原始 trace 保留在 `results-joint-control-*`。

输出包括：

- `trace/`：原始用户态与内核 CTF，包含 metadata，可导入 Babeltrace / Trace Compass。
- `boundaries.txt`：运行结束后打印保存的第 3 轮起止时间；相当于只看边界打点，并不是新的日志性能基准。
- `events.txt`：Babeltrace 解码文本。
- `events.jsonl`：按 CTF 时间轴解码的结构化事件。
- `analysis.json`：6 组状态链、完整时间戳、线程身份、CPU 归属和原始事件字段。
- `channel-statistics.txt` / `babeltrace-stderr.txt`：丢弃与解码检查。
- `environment.txt` / `source-sha256.txt`：环境和源码校验。

## 分析器怎样得出结论

`decode.py` 使用 Babeltrace 2 的 Python 绑定，读取两个域的 CTF 事件时间 `ns_from_origin`，不拿业务载荷的 `stamp_ns` 与内核时间直接相减。发现 CTF 丢事件/丢包消息就报错。

`analyze.py` 先按 scenario / trial / cycle 找到第 3 轮的 `wait_begin` 和 `wait_end`，由该事件的 actor_tid 确认控制线程；这个标识还须与 UST 的 vtid 一致。

随后在该区间中寻找：

1. `sched_switch` 的 prev_tid 等于控制线程，且 prev_state=1：本实验的 eventfd 读使线程进入 TASK_INTERRUPTIBLE。
2. `sched_wakeup` 的 tid 等于控制线程：控制线程被唤醒。
3. 此后的 `sched_switch` 的 next_tid 等于控制线程：它重新获得 CPU。

阻塞时间 = 唤醒 − 阻塞切出；就绪等待 = 重新切入 − 唤醒。两段之和必须等于这次离开 CPU 的总时间。

辅助线程启动时可能先抢占控制线程一次；那次切出的 prev_state 是可运行/抢占标记，不能误认作阻塞。分析器明确选择 TASK_INTERRUPTIBLE 的那次切出，不把所有非零 prev_state 都当成阻塞。

最后，分析器检查唤醒到切入期间该 CPU 的 sched_switch 链，确认当时被调度的线程是谁。这是调度层面的归属，未采 IRQ 事件，不能把整个区间逐纳秒都解释成辅助线程的用户代码。

缺少唤醒、重复业务阶段、缺少切入或 CPU 切换链断裂，都会导致失败。分析器针对这个受控单次 eventfd 阻塞场景，不是可用于任意程序的通用调度分析器。

## 看原始证据

发布包保留本次实验完整的 `results/trace/`。在安装了 Python bt2 的 Linux 上，可重新解码分析：

```bash
python3 decode.py results/trace replay.jsonl
python3 analyze.py replay.jsonl replay-analysis.json
```

没有 bt2 时，也可以只用标准 Python 重算已交付的 JSONL：

```bash
python3 analyze.py results/events.jsonl replay-analysis.json
```

Trace Compass 12.1.0 已实际导入并复查这份 CTF，截图用三个原生书签标出阻塞、唤醒和重新获得 CPU 的位置。完整点击步骤、时间坐标、线程过滤注意事项见 [界面分析指南](../docs/trace-compass.md)。

## 结果范围

这是 QEMU/KVM 中真实采集的用户态与内核事件。来宾内核使用 PREEMPT_DYNAMIC，线程使用 SCHED_FIFO；它不是 PREEMPT_RT 内核测试，更不是硬件实时性保证。注入几十毫秒延迟是为了清楚展示两种状态，不能把这些值当成真实设备的典型开销。

文章前面的 70 次日志性能对比仍来自原 WSL2 环境，不能把这两个实验混为同一组性能数据。


## 本次实际结果

2026-10-18：共 2,472 条事件，UST 156 条，sched_switch 1,457 条，sched_wakeup 814 条，其余 45 条为 sched_wakeup_new。两个通道丢弃 0，CTF 解码未发现丢失消息。

| 场景 | 次数 | 周期耗时 ms | 阻塞 ms | 就绪等待 ms |
|---|---:|---:|---:|---:|
| blocked | 1 | 40.391913 | 40.258699 | 0.090743 |
| blocked | 2 | 41.338283 | 41.058315 | 0.236481 |
| blocked | 3 | 41.217932 | 41.097934 | 0.082192 |
| ready | 1 | 40.241043 | 20.126224 | 20.054217 |
| ready | 2 | 40.684746 | 20.584401 | 20.041978 |
| ready | 3 | 40.832013 | 20.746990 | 20.046426 |

这里的周期耗时取 CTF 中 cycle_begin/end 的时间。boundaries.txt 使用进入埋点前保存的单调时钟值，两者存在微小测量位置差异；不应混用两套时间字段做跨域相减。

本次 LTTng 调度字段的 prio 为 `task->prio - MAX_RT_PRIO`，因此 FIFO 50/70 在 trace 中显示为 -51/-71，不是配置成了负的用户优先级。`prev_state` 的抢占标记也不能被当成睡眠；字段语义应查本次模块源码。
