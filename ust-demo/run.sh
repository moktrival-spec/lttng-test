#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
for tool in cc pkg-config lttng babeltrace2 python3; do
    command -v "$tool" >/dev/null || { printf 'Missing command: %s\n' "$tool" >&2; exit 1; }
done
cc -O2 -Wall -Wextra -Werror -I. demo.c demo-tp.c \
    $(pkg-config --cflags --libs lttng-ust) -ldl -o demo
session="control-loop-$$"
trace_dir="$PWD/trace-$session"
events_file="$PWD/events-$session.txt"
lttng create "$session" --output="$trace_dir"
cleanup() { lttng destroy "$session" >/dev/null 2>&1 || true; }
trap cleanup EXIT
lttng enable-channel --session="$session" --userspace \
    --subbuf-size=64K --num-subbuf=4 ust
lttng enable-event --session="$session" --userspace --channel=ust 'control:*'
lttng add-context --session="$session" --userspace --channel=ust --type=vpid --type=vtid
lttng start "$session"
./demo
lttng stop "$session"
lttng list "$session"
lttng destroy "$session"
trap - EXIT
babeltrace2 "$trace_dir" | tee "$events_file"
python3 analyze.py "$events_file"
printf 'Trace saved in %s\n' "$trace_dir"
