"""Validate and analyze the 10-cycle demo's Babeltrace text (not a benchmark)."""
import json
from pathlib import Path
import re
import sys

source = Path(sys.argv[1])
phases = {}
count = 0
last_stamp = -1
for line in source.read_text(encoding='utf-8').splitlines():
    if 'control:phase:' not in line:
        continue
    match = re.search(r'cycle = (\d+), phase = "([^"]+)", release_ns = (\d+), stamp_ns = (\d+)', line)
    if not match:
        raise SystemExit('Cannot parse a control:phase record')
    cycle, phase, release, stamp = match.groups()
    cycle, release, stamp = int(cycle), int(release), int(stamp)
    if stamp < last_stamp:
        raise SystemExit('Non-monotonic event stamps')
    last_stamp = stamp
    key = (cycle, phase)
    if key in phases:
        raise SystemExit(f'Duplicate phase: {key}')
    phases[key] = (release, stamp)
    count += 1

required = {(c, p) for c in range(1, 11) for p in ['begin', 'compute_end', 'end']}
if set(phases) != required:
    raise SystemExit(f'Incomplete/unexpected phases: missing={required-set(phases)}, extra={set(phases)-required}')
rows = []
previous_release = None
for cycle in range(1, 11):
    values = [phases[(cycle, p)] for p in ['begin', 'compute_end', 'end']]
    release = values[0][0]
    begin, compute, end = [v[1] for v in values]
    if not all(v[0] == release for v in values) or not release <= begin <= compute <= end:
        raise SystemExit('Invalid phase order or release time')
    if previous_release is not None and release - previous_release != 1000000:
        raise SystemExit('Planned release spacing is not 1 ms')
    previous_release = release
    rows.append({'cycle':cycle, 'late_ms':(begin-release)/1e6,
                 'compute_ms':(compute-begin)/1e6, 'output_ms':(end-compute)/1e6,
                 'exec_ms':(end-begin)/1e6, 'response_ms':(end-release)/1e6,
                 'deadline_missed':end-release > 1000000})
summary = {'events':count, 'complete_cycles':len(rows), 'period_ms':1,
           'missing_phases':0, 'duplicate_phases':0,
           'deadline_misses':sum(r['deadline_missed'] for r in rows), 'cycles':rows}
target = source.with_suffix('.summary.json')
target.write_text(json.dumps(summary, indent=2)+'\n', encoding='utf-8')
print(f'events={count} complete_cycles={len(rows)}')
print('cycle late_ms output_ms response_ms')
for r in rows:
    print(f"{r['cycle']:5d} {r['late_ms']:7.3f} {r['output_ms']:9.3f} {r['response_ms']:11.3f}")
print(f"deadline_misses={summary['deadline_misses']}")
print(f'Summary: {target}')
