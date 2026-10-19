# LTTng / spdlog 周期负载实测

本目录是 2026-10-17 实际执行的实验源码与逐次指标。它验证的是 **WSL2 上的用户态记录路径**，没有运行 PREEMPT_RT、SCHED_FIFO、内核追踪、设备 I/O 或真实控制算法。

## 文件

- `bench.cpp`、`bench-tp.cpp`、`bench-tp.h`：同一可执行程序的七种模式。
- `runner.py`：本次使用的隔离环境运行脚本；随机顺序、准备握手、采集、排空与记录核验。
- `build-isolated.sh`：本次使用的构建脚本。
- `summarize.py`：从 70 次逐次指标生成汇总 JSON 与 CSV，不丢弃异常轮次。
- `results/all-runs.json`：70 次运行的原始统计输出及计数核验；各次 JSON 同时单独保留。
- `results/summary.csv`、`summary.json`：五轮中位数、最小值、最大值；JSON 还保留五个原值。
- `results/environment.json`、`run-order.json`：环境与实际运行顺序。
- `results/count-check.json`：对已保存的逐次计数做算术复核，不能替代原始事件审计。

这里的“原始统计输出”是逐次运行返回的统计量，不是所有逐事件时间样本。程序在内存中保存每个调用和周期的样本，排序计算分位数后释放。完整 CSV 日志和 CTF 流使用 Linux 临时目录，后续检查时这些临时文件已不再存在，未长期留存。全部文件解析、计数和断言是在每次运行结束、文件仍在时完成，并即时保存为 JSON；没有完成后续对原始事件文件的第二次审计。

## 工作负载

4 个生产线程，各执行 8 轮预热、2,000 个测量周期，周期为 1 ms。预热后等待 200 ms 排空，外部准备握手完成后，以未来 100 ms 为统一起点。每线程固定在一个 CPU：0、2、4、6；整个实验进程树、后台日志线程、sessiond 和 consumerd 的可用 CPU 集合为 0、2、4、6、8、10。没有给消费者独占 CPU，没有配置实时优先级或 mlockall。虚拟 CPU 编号不保证对应独立物理核心。

每周期执行 16,384 次同样的 xorshift 整数更新，最终 checksum 对外输出。70 次运行的 checksum 全部一致。低密度为 1 个阶段、2 个事件；高密度为 128 个阶段、256 个事件；每阶段前后各记录一次。阶段拆分不同，计算迭代总数相同。每种密度内部，各记录模式使用相同计算与计时方法。

所有事件包含五个业务字段：64 位序号、32 位工作线程编号、32 位阶段编号、64 位计算值、64 位单调时钟时间戳。LTTng 还会加入自身事件头和追踪时间戳。spdlog 用 `%v` 模式输出五字段 CSV，三个日志模式使用相同 basic_file_sink_mt。业务载荷相同，实际字节格式和内部元数据不同。

模式为 `none`、`ust-off`、`spdlog-off`、`sync`、`async-drop`、`async-block`、`lttng`。`none` 仍运行相同计时、分支和采样框架，且同一二进制仍链接 UST；它是空操作基线，不是完全移除所有测量代码的程序。关闭模式是已编译并链接但不输出记录；不能拿关闭成本冒充启用成本。

## 输出、缓冲和丢弃策略

所有定时输出写到 WSL Linux `/tmp` 下的 ext4 文件系统，未写 `/mnt/c`。`stat -f` 的原始报告为 ext2/ext3 文件系统家族名称；另用 `findmnt -T /tmp -n -o FSTYPE` 确认为 ext4。

同步 spdlog 在调用线程格式化并进入带互斥锁的普通文件 sink；stdio 有自己的缓冲。没有逐条 flush 或 fsync。异步 spdlog 使用一个后台线程，前端仍格式化消息，再进入共享队列；`discard_new` 满时丢新记录，`block` 满时等待。丢新模式也需要队列同步，不等于完全无锁或永不等待。

LTTng 通道为 per-user、per-CPU、discard，每 CPU 4 个 64 KiB 子缓冲。20 个在线 CPU 的名义数据区为 5 MiB，不含元数据、消费者等额外开销；固定的 4 个生产 CPU 只使用其中相应的缓冲。spdlog 的 async_msg 实测为 408 字节，共享队列容量为 12,849，内部 12,850 个槽位约占 5 MiB。这是相近的名义预算，并非精确匹配可用记录容量，也不是总 RSS 测量。

同步日志没有这块异步队列。CTF 与 CSV、按 CPU 缓冲与共享队列、多个流文件与单个 sink 文件的差异，都是本次实际配置的一部分。不能把结果解释为纯队列算法性能，更不能推广到所有异步日志库。

结束时，spdlog 等后台线程处理完队列并 flush；LTTng stop 后由 destroy 完成会话收尾，再用 Babeltrace 读取。没有做掉电持久性测试。输出字节数为可见文件长度，包含预热和 CTF 元数据/包填充，不是物理设备写入量。

## 计时与完整性

- 调用时间：记录函数前后的 CLOCK_MONOTONIC 间隔；包括计时框架开销，报告空操作基线，不当成纯函数指令成本。
- service：周期实际开始到结束。
- response：周期计划释放到结束，包含晚唤醒和积压。绝对计划时间每次增加 1 ms，超期后不重置，所有计划周期都执行和计入。
- deadline_misses：response > 1 ms 的周期数，每次测量共 8,000 个周期。
- p99、p99.9：每次运行内按 nearest-rank 计算；汇总的是五次分位数的中位数，未把它冒充全部样本合并后的分位数。
- self_cpu_s：测量阶段到本进程输出排空的 getrusage，包含异步工作线程；不含预热、排序和离线解析。
- external_cpu_s：私有 sessiond 及其子进程的 /proc CPU 计数差，测量前到停止并排空后。计数粒度为系统时钟 tick，本次为 10 ms。
- pipeline_cpu_s：上述两者相加。它是总 CPU 时间，多个核心并行时可大于墙钟时间。未单独测 RSS、能耗或内核追踪成本。

spdlog 文件逐行解析五个字段，通过序号检查范围、重复、预热数量与实际测量数量；未发现重复记录。LTTng 使用 Babeltrace counter sink 统计实际可解码的事件数，与期望总数、通道丢弃计数核对；预热结束后的丢弃计数为 0。本次没有逐条审计 CTF 序号，因此不声称完成了 CTF 序号去重检查。

全部记录模式均满足：期望总数 − 实际记录数 = 丢弃计数。预热单独使用高位序号；每次低密度期望 16,064 条，高密度期望 2,056,192 条，均包含预热。

## 主要结果及局限

高密度异步丢新模式的一轮丢失 18,606 条，其他轮次为 0；该轮丢失率约 0.905%，五轮合计约 0.181%。该轮周期 p99 为 5.512 ms，实际 service p99 为 0.926 ms，说明只看 service 会漏掉相当多的晚唤醒和积压。本次未录制调度事件，不能进一步断言是哪种系统调度因素造成该异常。

同步、异步阻塞和 LTTng 在两档、各五轮中均未观察到丢失。零丢失只描述这些有限运行；没有证明更高事件率或消费者长时间停顿时仍不丢。

结果不能证明硬实时能力。所有模式在 70 次实验中都出现过超期周期；WSL 宿主负载、虚拟化、频率变化与普通调度都可能影响尾部。低密度下有的指标与基线差异落在运行波动范围内，不应解释为“加埋点使系统更快”或“零成本”。

## 复现本次隔离环境

以下目录布局对应本次实际使用的脚本：

```text
lttng-latency/
  deps/usr/              # 解包的 Ubuntu 依赖
  benchmark/
    bench.cpp ...
    spdlog-1.15.3/
    runner.py
```

在 Ubuntu 24.04 中准备本地依赖目录，使用 `apt-get download` 下载发行版官方包，再用 `dpkg-deb -x` 解包到 `deps/`。本次的包为 lttng-tools、liblttng-ctl0t64、liblttng-ust-common1t64、liblttng-ust-ctl5t64、liblttng-ust1t64、liblttng-ust-dev、liburcu8t64、liburcu-dev、libpopt0、babeltrace2、libbabeltrace2-0、libnuma1。版本见环境文件；未修改系统安装状态。

将 spdlog 官方 v1.15.3 归档解压到 `benchmark/`：
https://github.com/gabime/spdlog/archive/refs/tags/v1.15.3.tar.gz

下载归档 SHA256：`15a04e69c222eb6c01094b5c7ff8a249b36bb22788d72519646fb85feb267e67`。

```bash
bash build-isolated.sh
python3 runner.py --pilot --repeats 1 --cycles 200
python3 runner.py --repeats 5 --cycles 2000
python3 summarize.py
```

runner.py 是本次实际执行的脚本，环境标签、CPU 列表和 408 字节槽位检查均针对本机。换机器复现前，更新 metadata 中的硬件、内核、UST 版本及缓冲预算，按实际可用 CPU 同时修改 runner 和 bench.cpp 的亲和性；不要保留本机标签后当成新机器结果。正式结果目录已有数据，重跑前应先复制留存，或修改 RESULT 为新目录。需要保存完整原始事件时，应将 RUN 改为持久的 Linux ext4 目录，或在 WSL 退出前把临时输出归档；勿在计时期间改用 /mnt/c 输出。脚本会为本次测试建立专用会话守护进程，并仅在退出时终止该私有守护进程。

若依赖已按系统方式安装，可以用 pkg-config 提供 UST 的编译/链接参数，移除隔离路径设置，并让 sessiond 使用默认 consumerd 路径；这是迁移说明，本次实际测试采用上面的隔离构建流程。

## 一手实现依据

- spdlog 的 async_overflow_policy（v1.15.3）：https://github.com/gabime/spdlog/blob/v1.15.3/include/spdlog/async_logger.h
- 队列与丢新计数：https://github.com/gabime/spdlog/blob/v1.15.3/include/spdlog/details/mpmc_blocking_q.h
- 后台线程与排空退出：https://github.com/gabime/spdlog/blob/v1.15.3/include/spdlog/details/thread_pool-inl.h
- 文件 sink：https://github.com/gabime/spdlog/blob/v1.15.3/include/spdlog/sinks/basic_file_sink-inl.h
- LTTng 通道配置：https://raw.githubusercontent.com/lttng/lttng-tools/stable-2.13/doc/man/lttng-enable-channel.1.txt
