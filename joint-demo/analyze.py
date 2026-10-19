"""Correlate this controlled demo's UST phases with actual scheduler records.

Uses CTF event timestamps, not the application's delay configuration. Fails if
the single eventfd-block / wakeup / switch-in chain cannot be established.
This is deliberately a small scenario-specific analyzer, not a general scheduler.
"""
import json,sys
from pathlib import Path

events=[json.loads(line) for line in Path(sys.argv[1]).read_text().splitlines() if line]
events.sort(key=lambda e:e['ts_ns'])
ust=[e for e in events if e['name']=='control:phase']
switches=[e for e in events if e['name']=='sched_switch']
wakes=[e for e in events if e['name']=='sched_wakeup']
assert ust and switches and wakes, 'Need both UST and kernel scheduling events'

def p(e,key):return e['payload'][key]
def tid(e,key):
    for k in (key+'_tid',key+'_pid'):
        if k in e['payload']:return p(e,k)
    raise AssertionError('Missing task identity in sched_switch')
def wake_tid(e):
    for key in ['tid','pid']:
        if key in e['payload']:return p(e,key)
    raise AssertionError('Missing target identity in sched_wakeup')
def cpu(e):return e['packet']['cpu_id']
def one(items,label):
    assert len(items)==1,f'{label}: expected one event, got {len(items)}'
    return items[0]
def span(a,b):return (b['ts_ns']-a['ts_ns'])/1e6

results=[]
for scenario,trial in sorted({(p(e,'scenario'),p(e,'trial')) for e in ust}):
    group=[e for e in ust if (p(e,'scenario'),p(e,'trial'))==(scenario,trial)]
    def phase(name,cycle=3):
        return one([e for e in group if p(e,'phase')==name and p(e,'cycle')==cycle],name)
    begin,end=phase('cycle_begin'),phase('cycle_end')
    before,after=phase('wait_begin'),phase('wait_end')
    emit=phase('wake_emit')
    target=p(begin,'actor_tid');helper=p(emit,'actor_tid')
    assert target!=helper
    assert all(e['context']['vtid']==p(e,'actor_tid') for e in group)
    for cycle in range(1,11):
        phase('cycle_begin',cycle);phase('cycle_end',cycle)
    # Ignore the runnable preemption when the control thread starts the helper.
    # The actual eventfd read switches out with TASK_INTERRUPTIBLE (1).
    out=one([e for e in switches if before['ts_ns']<=e['ts_ns']<=after['ts_ns']
             and tid(e,'prev')==target and p(e,'prev_state')==1], 'interruptible block')
    wake=one([e for e in wakes if out['ts_ns']<e['ts_ns']<after['ts_ns']
              and wake_tid(e)==target], 'wakeup of control thread')
    ins=[e for e in switches if wake['ts_ns']<=e['ts_ns']<=after['ts_ns'] and tid(e,'next')==target]
    switch_in=one(ins,'switch-in after wakeup')
    assert cpu(out)==cpu(switch_in)==cpu(wake)==cpu(emit), 'Expected pinned same-CPU experiment'
    assert before['ts_ns']<=out['ts_ns']<wake['ts_ns']<=switch_in['ts_ns']<=after['ts_ns']
    # At the wakeup the CPU's current scheduled task is the helper. Sum its
    # scheduled intervals until control runs. IRQs are not separated here.
    cpu_events=[e for e in switches if cpu(e)==cpu(wake)]
    previous=[e for e in cpu_events if e['ts_ns']<=wake['ts_ns']]
    assert previous
    running=tid(previous[-1],'next')
    assert running==helper, 'Waker helper must own this CPU at wakeup'
    cursor=wake['ts_ns'];helper_ns=0;owners=[]
    for e in cpu_events:
        if not wake['ts_ns']<e['ts_ns']<=switch_in['ts_ns']:continue
        assert tid(e,'prev')==running,'CPU switch chain is incomplete'
        owners.append({'tid':running,'start_ns':cursor,'end_ns':e['ts_ns']})
        if running==helper:helper_ns+=e['ts_ns']-cursor
        cursor=e['ts_ns'];running=tid(e,'next')
    assert cursor==switch_in['ts_ns'] and running==target
    selected=[begin,before,out,emit,wake,switch_in,after,end]
    if scenario=='ready':selected += [phase('hog_begin'),phase('hog_end')]
    selected.sort(key=lambda e:e['ts_ns'])
    evidence=[{'relative_ms':(e['ts_ns']-out['ts_ns'])/1e6,
               'name':e['name'],'cpu':cpu(e),'payload':e['payload']} for e in selected]
    result={'scenario':scenario,'trial':trial,'control_tid':target,'helper_tid':helper,
            'cpu':cpu(out),'cycle_elapsed_ms':span(begin,end),
            'wait_boundary_ms':span(before,after),'blocked_ms':span(out,wake),
            'runnable_ms':span(wake,switch_in),'off_cpu_ms':span(out,switch_in),
            'helper_scheduled_while_runnable_ms':helper_ns/1e6,
            'switch_out_ns':out['ts_ns'],'wakeup_ns':wake['ts_ns'],
            'switch_in_ns':switch_in['ts_ns'],'prev_state':p(out,'prev_state'),
            'control_kernel_prio':p(out,'prev_prio'),'helper_kernel_prio':p(previous[-1],'next_prio'),
            'cpu_owners_after_wakeup':owners,'evidence':evidence}
    assert abs(result['blocked_ms']+result['runnable_ms']-result['off_cpu_ms'])<1e-8
    results.append(result)
report={'event_count':len(events),'ust_events':len(ust),'sched_switch_events':len(switches),
        'sched_wakeup_events':len(wakes),'cases':results,
        'interpretation':'Blocked interval = interruptible switch-out to target wakeup; runnable interval = wakeup to switch-in. CPU ownership is scheduler-level; IRQ time not separated.',
        'clock':'Babeltrace CTF ns_from_origin for both domains; payload stamp_ns not used for cross-domain subtraction.'}
Path(sys.argv[2]).write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
print('scenario trial cycle_ms blocked_ms runnable_ms helper_ms')
for r in results:
    print(f"{r['scenario']:8s} {r['trial']:5d} {r['cycle_elapsed_ms']:8.3f} {r['blocked_ms']:10.3f} {r['runnable_ms']:11.3f} {r['helper_scheduled_while_runnable_ms']:9.3f}")
print(f'Validated {len(results)} complete blocking/wakeup/switch-in chains')
