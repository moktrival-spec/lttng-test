#!/bin/bash
set -euo pipefail
build_dir="${MODULE_BUILD_DIR:-$PWD/module-build}"
mkdir -p "$build_dir"
cd "$build_dir"
curl -fL --retry 2 https://lttng.org/files/lttng-modules/lttng-modules-2.13.23.tar.bz2 -o lttng-modules-2.13.23.tar.bz2
curl -fL https://lttng.org/files/lttng-modules/lttng-modules-2.13.23.tar.bz2.sha256 -o lttng-modules-2.13.23.tar.bz2.sha256
sha256sum -c lttng-modules-2.13.23.tar.bz2.sha256
tar -xf lttng-modules-2.13.23.tar.bz2
cd lttng-modules-2.13.23
cp src/probes/Kbuild src/probes/Kbuild.original
# Lab scope: keep only scheduling and state-dump probes. The distribution
# kernel backported a timer tracepoint ABI change; that unrelated probe fails.
# No scheduler event definitions or timestamp paths are changed.
head -n 9 src/probes/Kbuild.original > src/probes/Kbuild
printf '\nobj-$(CONFIG_LTTNG) += lttng-probe-statedump.o\n' >> src/probes/Kbuild
python3 - <<'PY'
from pathlib import Path
original=Path('src/probes/Kbuild.original').read_text()
helpers=original.split('ifneq ($(CONFIG_KPROBES),)',1)[1].split('ifneq ($(CONFIG_PREEMPTIRQ_EVENTS),)',1)[0]
with Path('src/probes/Kbuild').open('a') as out:
    out.write('\nifneq ($(CONFIG_KPROBES),)'+helpers)
PY
make -j1
sudo make modules_install
sudo depmod -a
sudo modprobe lttng-tracer
modinfo lttng-tracer | head -n 12
sudo lttng list --kernel > "$build_dir/kernel-events.txt"
grep -E 'sched_switch|sched_wakeup' "$build_dir/kernel-events.txt"
