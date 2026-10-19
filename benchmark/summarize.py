from pathlib import Path
import json,csv,statistics as s
root=Path(__file__).resolve().parent
runs=json.loads((root/'results/all-runs.json').read_text())
assert len(runs)==70
assert len(set(r['checksum'] for r in runs))==1
fields={'call_mean_ns':lambda r:r['call']['mean_ns'],'call_p99_ns':lambda r:r['call']['p99_ns'],
 'service_p99_ns':lambda r:r['service']['p99_ns'],'response_p99_ns':lambda r:r['response']['p99_ns'],
 'response_p999_ns':lambda r:r['response']['p999_ns'],'response_max_ns':lambda r:r['response']['max_ns'],
 'pipeline_cpu_s':lambda r:r['pipeline_cpu_s'],'self_cpu_s':lambda r:r['self_cpu_s'],
 'output_bytes':lambda r:r['output_bytes'],'miss_percent':lambda r:r['deadline_misses']/(r['cycles_per_thread']*r['threads'])*100,
 'loss_percent':lambda r:r.get('missing_records',0)/r.get('expected_records',1)*100}
summary=[]
for stages in (1,128):
 for mode in ['none','ust-off','spdlog-off','sync','async-drop','async-block','lttng']:
  group=[r for r in runs if r['stages']==stages and r['mode']==mode];assert len(group)==5
  row={'stages':stages,'mode':mode,'repeats':5}
  for key,fn in fields.items():
   v=[fn(r) for r in group];row[key]={'median':s.median(v),'min':min(v),'max':max(v),'values':v}
  row['missing_total']=sum(r.get('missing_records',0) for r in group)
  row['expected_total']=sum(r.get('expected_records',0) for r in group)
  row['runs_with_loss']=sum(r.get('missing_records',0)>0 for r in group)
  row['deadline_misses_total']=sum(r['deadline_misses'] for r in group)
  row['count_reconciled']=all(r.get('count_reconciled',True) for r in group)
  summary.append(row)
(root/'results/summary.json').write_text(json.dumps(summary,indent=2))
with (root/'results/summary.csv').open('w',newline='') as f:
 keys=['stages','mode','repeats','missing_total','expected_total','runs_with_loss','deadline_misses_total']+[f'{key}_{suffix}' for key in fields for suffix in ['median','min','max']]
 writer=csv.DictWriter(f,fieldnames=keys);writer.writeheader()
 for row in summary:
  flat={key:row[key] for key in keys if key in row}
  flat.update({f'{key}_{suffix}':row[key][suffix] for key in fields for suffix in ['median','min','max']})
  writer.writerow(flat)
for row in summary:
 print(row['stages'],row['mode'], 'call_us',round(row['call_mean_ns']['median']/1000,3),
       'p99_ms',[round(row['response_p99_ns'][k]/1e6,3) for k in ['median','min','max']],
       'CPU_s',round(row['pipeline_cpu_s']['median'],3),
       'miss%',round(row['miss_percent']['median'],3),'loss',row['missing_total'])
