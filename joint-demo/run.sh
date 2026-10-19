#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ $(id -u) != 0 ]]; then echo 'Run with sudo in the disposable Linux lab.' >&2; exit 1; fi
for tool in cc pkg-config lttng babeltrace2 python3; do command -v "$tool" >/dev/null; done
python3 -c 'import bt2'
CPU=${CPU:-1}
TRIALS=${TRIALS:-3}
cc -O2 -Wall -Wextra -Werror -pthread -I. joint.c joint-tp.c \
  $(pkg-config --cflags --libs lttng-ust) -ldl -o joint
session="joint-control-$$"
output="$PWD/results-$session"
mkdir -p "$output"
{
  uname -a
  cat /etc/os-release
  lttng --version
  pkg-config --modversion lttng-ust
  modinfo lttng-tracer | head -n 12
  lscpu
  echo "control_cpu=$CPU control_policy=SCHED_FIFO:50 helper_policy=SCHED_FIFO:70 trials=$TRIALS"
  cat /proc/sys/kernel/sched_rt_runtime_us
  cat /proc/sys/kernel/sched_rt_period_us
} > "$output/environment.txt"
lttng create "$session" --output="$output/trace"
cleanup() { lttng destroy "$session" >/dev/null 2>&1 || true; }
trap cleanup EXIT
lttng enable-channel --session="$session" --userspace --subbuf-size=256K --num-subbuf=4 user
lttng enable-event --session="$session" --userspace --channel=user 'control:*'
lttng add-context --session="$session" --userspace --channel=user --type=vpid --type=vtid
lttng enable-channel --session="$session" --kernel --subbuf-size=256K --num-subbuf=4 kernel
lttng enable-event --session="$session" --kernel --channel=kernel sched_switch,sched_wakeup,sched_wakeup_new
lttng start "$session"
for trial in $(seq 1 "$TRIALS"); do
  for scenario in blocked ready; do
    timeout 10s ./joint "$scenario" "$trial" "$CPU" | tee -a "$output/boundaries.txt"
  done
done
lttng stop "$session"
lttng list "$session" | tee "$output/channel-statistics.txt"
lttng destroy "$session"
trap - EXIT
babeltrace2 "$output/trace" > "$output/events.txt" 2> "$output/babeltrace-stderr.txt"
python3 decode.py "$output/trace" "$output/events.jsonl"
python3 analyze.py "$output/events.jsonl" "$output/analysis.json"
sha256sum joint.c joint-tp.c joint-tp.h run.sh decode.py analyze.py > "$output/source-sha256.txt"
printf 'Results: %s\n' "$output"
