# LTTng：控制线程的时间花在哪里

「机器与代码」LTTng 文章配套实验。核心问题：一个控制周期同样慢了约 40 ms，线程究竟一直在阻塞，还是早已就绪、却没有拿到 CPU？

## 从联合追踪示例开始

```bash
git clone https://github.com/moktrival-spec/lttng-test.git
cd lttng-test/joint-demo
```

按 [环境与操作说明](joint-demo/README.md) 准备 Linux、匹配当前内核的 LTTng 模块、LTTng-UST 与 Babeltrace 2，然后运行：

```bash
sudo bash run.sh
```

程序使用两个绑定同一 CPU 的 SCHED_FIFO 线程。控制线程优先级为 50，辅助线程为 70。A/B 各运行 3 次，只在第 3 轮注入延迟：A 等待约 40 ms 后被唤醒；B 约 20 ms 后被唤醒，但辅助线程继续占用 CPU 约 20 ms。

脚本在同一会话采集 `control:*`、`sched_switch`、`sched_wakeup` 和 `sched_wakeup_new`，按业务周期与线程 ID 关联，分别计算阻塞时间和就绪等待。

这段程序故意制造实时优先级竞争，请在独立 Linux 实验机中运行。

## 已保存的实际结果

QEMU/KVM，Ubuntu 24.04.5，Linux 6.8.0-147-generic PREEMPT_DYNAMIC，2 vCPU、4 GiB。它不是 PREEMPT_RT 内核或真实控制设备的实时性测试。

第一组结果：

| 场景 | 周期耗时 | 阻塞 | 就绪等待 |
|---|---:|---:|---:|
| A / blocked | 40.391913 ms | 40.258699 ms | 0.090743 ms |
| B / ready | 40.241043 ms | 20.126224 ms | 20.054217 ms |

六组一共采到 2,472 条事件，两个通道报告 0 丢弃。完整原始 CTF、解码事件、分析结果、环境和校验和均保存在 [joint-demo/results](joint-demo/results)。

只复算已有结果不需要 root，也不需要安装 LTTng：

```bash
python3 joint-demo/analyze.py \
  joint-demo/results/events.jsonl replay-analysis.json
```

## 在界面中看同一份 trace

![三个书签标出阻塞、唤醒与重新运行](docs/tracecompass-control-flow.jpg)

按 [Trace Compass 操作指南](docs/trace-compass.md) 导入两个 CTF 域、筛选线程并逐个核对状态边界。红色标签是手工添加的原生书签。

## 目录

- [joint-demo/](joint-demo/)：用户态埋点与内核调度联合追踪，建议先读。
- [ust-demo/](ust-demo/)：仅用户态埋点的入门示例。
- [benchmark/](benchmark/)：同步日志、异步日志与 LTTng 的性能对比源码和 70 次逐次指标。该组运行于 WSL2 / SCHED_OTHER，与联合追踪实验分开解读。
- [docs/trace-compass.md](docs/trace-compass.md)：Trace Compass 12.1 的实际操作步骤、带原生书签的截图和可直接定位的时间坐标。

## 如何理解证据

`wait_begin/end` 只能给出等待调用的总耗时。切出时的线程状态、内核唤醒目标和再次切入时刻，才能把总等待拆成阻塞和就绪等待。分析器在缺少关键事件时会失败，不把记录缺失当成真实延迟。

本仓库不包含虚拟机镜像、账号密钥或生产设备数据。原始记录来自专门为本实验创建的 Linux 来宾。
