#!/usr/bin/env python3
"""Isolated WSL runner; all timed output resides on Linux ext4, not /mnt/c."""
import argparse, json, os, pathlib, random, re, shutil, subprocess, time

p=argparse.ArgumentParser()
p.add_argument('--pilot',action='store_true')
p.add_argument('--repeats',type=int,default=5)
p.add_argument('--cycles',type=int,default=2000)
args=p.parse_args()
HERE=pathlib.Path(__file__).resolve().parent
DEPS=HERE.parent/'deps/usr'
os.environ.update(PATH=str(DEPS/'bin')+':'+os.environ['PATH'],
 LD_LIBRARY_PATH=str(DEPS/'lib/x86_64-linux-gnu'),
 BABELTRACE_PLUGIN_PATH=str(DEPS/'lib/x86_64-linux-gnu/babeltrace2/plugins'),
 LTTNG_SESSION_CONFIG_XSD_PATH=str(DEPS/'share/xml/lttng'))
import tempfile
RUN=pathlib.Path(tempfile.mkdtemp(prefix='lttng-benchmark-',dir='/tmp'))
os.environ['LTTNG_HOME']=str(RUN/'home');(RUN/'home').mkdir()
os.sched_setaffinity(0,{0,2,4,6,8,10})
RESULT=HERE/('pilot-results' if args.pilot else 'results')
RESULT.mkdir(exist_ok=True)
shutil.copy2(HERE/'bench',RUN/'bench')
def cmd(*argv):
 r=subprocess.run(list(map(str,argv)),capture_output=True,text=True,check=True)
 return r.stdout+r.stderr
def external_cpu():
 # Match only daemons owned by this private LTTNG_HOME, plus their descendants.
 pidfile=RUN/'home/.lttng/lttng-sessiond.pid'
 if not pidfile.exists():return 0.0
 root=int(pidfile.read_text()); ps={}
 for path in pathlib.Path('/proc').glob('[0-9]*/stat'):
  try:
   content=path.read_text(); tail=content[content.rindex(')')+2:].split()
   ps[int(path.parent.name)]=(int(tail[1]),int(tail[11])+int(tail[12]))
  except (FileNotFoundError,ProcessLookupError):pass
 selected={root}; changed=True
 while changed:
  old=len(selected);selected.update(pid for pid,(ppid,_) in ps.items() if ppid in selected)
  changed=len(selected)!=old
 return sum(ps[pid][1] for pid in selected if pid in ps)/os.sysconf('SC_CLK_TCK')
def loss(text):
 m=re.search(r'Discarded events:\s*(\d+)',text)
 if not m:raise RuntimeError('Missing discarded-event counter: '+text)
 return int(m.group(1))
def record_count(trace):
 # Counter sink avoids making CTF text formatting part of the benchmark.
 output=cmd('babeltrace2',trace,'--component=sink.utils.counter')
 (current/'ctf-counter.txt').write_text(output)
 values=re.findall(r'^\s*(\d+)\s+Event messages\b',output,re.M)
 if not values:raise RuntimeError('Cannot parse counter: '+output)
 return int(values[-1])
meta={'date':'2026-10-17','kernel':cmd('uname','-sr').strip(),
 'kernel_build':cmd('uname','-v').strip(),'preempt_rt':False,
 'distribution':'Ubuntu 24.04.4 / WSL2','cpu_model':'Intel Core i9-12900H (virtualized)',
 'online_cpus':os.cpu_count(),'affinity':[0,2,4,6,8,10],'producer_cpus':[0,2,4,6],
 'scheduler':'SCHED_OTHER; no RT priorities or mlockall',
 'output_filesystem':cmd('stat','-f','-c','%T',RUN).strip(),
 'lttng_tools':cmd('lttng','--version').strip(),'babeltrace':cmd('babeltrace2','--version').strip(),
 'ust':'2.13.7','spdlog':'1.15.3','compiler':cmd('g++','-dumpfullversion').strip(),
 'period_ns':1000000,'work_iterations_per_cycle':16384,'warmup_cycles':8,
 'cycles_per_thread':args.cycles,'repeats':args.repeats,'seed':20261017,
 'channel':{'subbuf_bytes':65536,'num_subbuf':4,'allocation':'per-user per-CPU','mode':'discard'},
 'queue_budget_bytes':20*65536*4,
 'measurement':'nearest-rank quantiles; no per-record fsync; final drain before counting; absolute scheduled release retained after overruns'}
(RESULT/'environment.json').write_text(json.dumps(meta,indent=2))
cmd('lttng-sessiond','--daemonize','--no-kernel',
 '--consumerd64-path='+str(DEPS/'lib/x86_64-linux-gnu/lttng/libexec/lttng-consumerd'),
 '--consumerd64-libdir='+str(DEPS/'lib/x86_64-linux-gnu'))
# sizeof(async_msg) is verified on the first run; 408 B for this GCC/spdlog build.
slots=meta['queue_budget_bytes']//408-1
modes=['none','ust-off','spdlog-off','sync','async-drop','async-block','lttng']
jobs=[(rep,stages,mode) for rep in range(args.repeats) for stages in (1,128) for mode in modes]
random.Random(meta['seed']).shuffle(jobs)
(RESULT/'run-order.json').write_text(json.dumps(jobs,indent=2))
results=[]
try:
 for index,(rep,stages,mode) in enumerate(jobs):
  name=f'{index:02d}-r{rep}-s{stages}-{mode}'
  current=RUN/name;current.mkdir()
  if mode=='lttng':
   cmd('lttng','create','bench','--output='+str(current/'trace'))
   cmd('lttng','enable-channel','--userspace','--buffers-uid','--subbuf-size=64K','--num-subbuf=4','--discard','ch')
   cmd('lttng','enable-event','--userspace','--channel=ch','bench:record')
   cmd('lttng','start','bench')
  stderr=open(current/'stderr.txt','w')
  proc=subprocess.Popen([str(RUN/'bench'),mode,str(stages),str(args.cycles),str(current),str(slots)],stdout=subprocess.PIPE,stderr=stderr,text=True)
  deadline=time.monotonic()+30
  while not (current/'ready').exists():
   if proc.poll() is not None or time.monotonic()>deadline:
    proc.kill();raise RuntimeError('Benchmark did not become ready: '+(current/'stderr.txt').read_text())
   time.sleep(.01)
  warmup_discard=0
  if mode=='lttng':warmup_discard=loss(cmd('lttng','list','bench'))
  cpu0=external_cpu();(current/'go').write_text('1')
  stdout,_=proc.communicate(timeout=180);stderr.close()
  if proc.returncode:raise RuntimeError(stdout+(current/'stderr.txt').read_text())
  data=json.loads(stdout)
  if data['async_msg_bytes']!=408:raise RuntimeError('Revise slots for measured async_msg size: '+str(data['async_msg_bytes']))
  if mode=='lttng':
   cmd('lttng','stop','bench');listing=cmd('lttng','list','bench')
   data['discard_counter']=loss(listing);data['warmup_discard_counter']=warmup_discard
   (current/'lttng-list.txt').write_text(listing)
  data['external_cpu_s']=external_cpu()-cpu0
  data['pipeline_cpu_s']=data['self_cpu_s']+data['external_cpu_s']
  if mode=='lttng':
   cmd('lttng','destroy','bench')
   data['written_records']=record_count(current/'trace')
  elif mode in ('sync','async-drop','async-block'):
   seen=bytearray(data['expected_measured']);warmup_seen=set();duplicate=0;actual=0
   with open(current/'records.csv') as f:
    for line in f:
     fields=line.rstrip().split(',')
     if len(fields)!=5:raise RuntimeError('Malformed record')
     seq,w,phase,value,stamp=map(int,fields);actual+=1
     if seq>=1<<63:
      duplicate+=seq in warmup_seen;warmup_seen.add(seq)
     else:
      if not 0<=seq<len(seen):raise RuntimeError('Out of range seq')
      duplicate+=seen[seq];seen[seq]=1
   data.update(written_records=actual,written_measured=sum(seen),written_warmup=len(warmup_seen),duplicate_records=duplicate)
  else:data['written_records']=0
  data['output_bytes']=sum(f.stat().st_size for f in current.rglob('*') if f.is_file() and (f.name=='records.csv' or 'trace' in f.parts))
  data.update(repeat=rep,order=index)
  if mode in ('sync','async-drop','async-block','lttng'):
   data['expected_records']=data['expected_measured']+data['expected_warmup']
   data['missing_records']=data['expected_records']-data['written_records']
   data['count_reconciled']=data['missing_records']==data['discard_counter']
   assert data['count_reconciled'], data
   assert not data.get('warmup_discard_counter',0)
   if 'written_warmup' in data: assert data['written_warmup']==data['expected_warmup']
  assert data['affinity_ok']
  (RESULT/(name+'.json')).write_text(json.dumps(data,indent=2))
  results.append(data)
  print(f'{index+1}/{len(jobs)} {mode} stages={stages}: call {data["call"]["mean_ns"]:.0f} ns, response p99 {data["response"]["p99_ns"]/1e6:.3f} ms, loss {data.get("missing_records",0)}',flush=True)
  time.sleep(.2)
 (RESULT/'all-runs.json').write_text(json.dumps(results,indent=2))
 print('Raw files retained at '+str(RUN),flush=True)
finally:
 pidfile=RUN/'home/.lttng/lttng-sessiond.pid'
 if pidfile.exists():
  try:os.kill(int(pidfile.read_text()),15)
  except ProcessLookupError:pass
