"""Build report tables and PNG/SVG plots from actual study evidence only."""
import argparse
import csv
from datetime import datetime
import json
import os
from pathlib import Path
import statistics


def quantity(value):
    for suffix, factor in [('Gi',1024**3),('Mi',1024**2),('Ki',1024),('n',1e-9),('u',1e-6),('m',.001)]:
        if value.endswith(suffix): return float(value[:-len(suffix)])*factor
    return float(value)


def resources(samples,target='waiting-room'):
    cpu=[];memory=[];ready=[];errors=0
    for sample in samples:
        pods={p['metadata']['name']:p['metadata'].get('labels',{}).get('app') for p in sample.get('pods',{}).get('items',[])}
        items=[p for p in sample.get('metrics',{}).get('items',[]) if pods.get(p['metadata']['name'])==target]
        if items:
            cpu.append(sum(quantity(c['usage']['cpu'])*1000 for p in items for c in p['containers']))
            memory.append(sum(quantity(c['usage']['memory'])/1024**2 for p in items for c in p['containers']))
        d=next((d for d in sample.get('deployments',{}).get('items',[]) if d['metadata']['name']==target),None)
        if d:ready.append(d['status'].get('readyReplicas',0))
        errors+=len(sample.get('errors',{}))
    return dict(mean_cpu_millicores=statistics.mean(cpu) if cpu else None,
        peak_memory_mib=max(memory) if memory else None, min_ready=min(ready) if ready else None,
        max_ready=max(ready) if ready else None, observation_errors=errors)


def export_pod_metrics(runs,output):
    fields=['run','collected_at','metrics_timestamp','metrics_window','pod','app','container',
            'cpu_raw','memory_raw','cpu_millicores','memory_mib','deployment_ready_replicas',
            'hpa_desired_replicas','waiting_queued','allocation_queued','allocation_in_progress',
            'allocation_retry','allocation_blocked','host_available_commit_bytes']
    with (output/'pod-metrics.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        for run in runs:
          for path in run.rglob('timeline.json'):
            for s in json.loads(path.read_text()):
                apps={p['metadata']['name']:p['metadata'].get('labels',{}).get('app') for p in s.get('pods',{}).get('items',[])}
                ready={d['metadata']['name']:d.get('status',{}).get('readyReplicas',0) for d in s.get('deployments',{}).get('items',[])}
                desired={h['spec']['scaleTargetRef']['name']:h.get('status',{}).get('desiredReplicas') for h in s.get('hpa',{}).get('items',[])}
                for pod in s.get('metrics',{}).get('items',[]):
                    app=apps.get(pod['metadata']['name'])
                    for c in pod['containers']:
                        writer.writerow(dict(run=str(path.parent),collected_at=s['at'],metrics_timestamp=pod.get('timestamp'),
                            metrics_window=pod.get('window'),pod=pod['metadata']['name'],app=app,container=c['name'],
                            cpu_raw=c['usage']['cpu'],memory_raw=c['usage']['memory'],
                            cpu_millicores=quantity(c['usage']['cpu'])*1000,memory_mib=quantity(c['usage']['memory'])/1024**2,
                            deployment_ready_replicas=ready.get(app),hpa_desired_replicas=desired.get(app),
                            waiting_queued=s.get('waiting_queue',{}).get('queued_count'),
                            allocation_queued=s.get('backlog',{}).get('QUEUED'),allocation_in_progress=s.get('backlog',{}).get('IN_PROGRESS'),
                            allocation_retry=s.get('backlog',{}).get('RETRY'),allocation_blocked=s.get('backlog',{}).get('BLOCKED'),host_available_commit_bytes=s.get('host',{}).get('available_commit_bytes')))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runs',nargs='+',type=Path)
    parser.add_argument('--output',type=Path,default=Path('output/validation/tc-fixes/report'))
    args=parser.parse_args()
    os.environ.setdefault('MPLCONFIGDIR',str(Path(__file__).resolve().parents[1]/'.local/matplotlib'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'figure.dpi':150})
    args.output.mkdir(parents=True,exist_ok=True)
    export_pod_metrics(args.runs,args.output)
    records=[]
    for run in args.runs:
        for path in sorted(run.rglob('summary.json')):
            r=json.loads(path.read_text())
            if 'offered' not in r:continue
            row={key:r.get(key) for key in ('status','rate','duration','profile','offered','scheduled','launched','accepted','rejected','timed_out','http_success','http_failed','generator_dropped','upstream_retries','upstream_attempts_known','average_response_ms','p95_ms','max_launch_lag_seconds','achieved_registration_rps','replicas','repeat','distinct_serving_replicas','sustainable')}
            row['path']=str(path)
            row['run']=run.name
            row['generator_clock']=r.get('generator',{}).get('clock','not recorded; see run notes')
            row['clock_resolution_seconds']=r.get('generator',{}).get('clock_resolution_seconds')
            row['generator_preparation_seconds']=r.get('generator',{}).get('preparation_seconds')
            row['arrival_started_at']=r.get('generator',{}).get('arrival_started_at')
            timeline=path.parent/'timeline.json'
            samples=json.loads(timeline.read_text()) if timeline.exists() else []
            row.update(resources(samples))
            for app in ('frontend','redis','postgres'):
                shared=resources(samples,app)
                row[app+'_mean_cpu_millicores']=shared['mean_cpu_millicores']
                row[app+'_peak_memory_mib']=shared['peak_memory_mib']
            row['sql_violations']=r.get('invariants',{}).get('violations')
            row['missing_ids']=len(r.get('missing_acknowledged_ids',[]))
            row['unresolved']=len((r.get('admission') or {}).get('unresolved_ids',[])) if r.get('admission') else None
            records.append(row)
        if (run/'phases.json').exists() and (run/'timeline.json').exists():
            hpa_plot(run,args.output,plt)
    if records:
        with (args.output/'runs.csv').open('w',newline='',encoding='utf-8') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(records[0]));writer.writeheader();writer.writerows(records)
    fixed=[r for r in records if r.get('replicas') and r['rate']==50]
    capacity=[r for r in records if r.get('replicas') and r['rate']!=50]
    if fixed:
        fig,axes=plt.subplots(1,2,figsize=(10,4),layout='constrained')
        for ax,key,title in zip(axes,('achieved_registration_rps','p95_ms'),('Accepted registrations / second','P95 HTTP latency (ms)')):
            for r in fixed: ax.scatter(r['replicas'],r[key],c='#147d92' if r['status']=='PASS' else '#be4b35',alpha=.8,
                                      label='Individual trials' if r is fixed[0] else None)
            counts=[n for n in (1,2,4) if any(r['replicas']==n for r in fixed)]
            means=[statistics.mean(r[key] for r in fixed if r['replicas']==n) for n in counts]
            ax.plot(counts,means,color='#24465e',label='Mean of all recorded trials')
            ax.set(xticks=[1,2,4],xlabel='Ready API replicas',ylabel=title,title=title);ax.grid(alpha=.2)
            ax.set_ylim(bottom=0)
            if key=='achieved_registration_rps':
                ax.set_ylim(0,55);ax.axhline(50,ls='--',color='gray',label='Offered 50/s')
            ax.legend(fontsize=8,loc='lower left')
        fig.suptitle('TC-23: 50 arrivals/s for 30 seconds (all trials retained)')
        save(fig,args.output/'tc23-fixed',plt)
        fig,axes=plt.subplots(1,2,figsize=(10,4),layout='constrained')
        for ax,key,title in zip(axes,('mean_cpu_millicores','peak_memory_mib'),
                               ('Mean total API CPU (millicores)','Peak total API memory (MiB)')):
            for r in fixed:
                if r[key] is not None:ax.scatter(r['replicas'],r[key],color='#147d92',alpha=.8)
            ax.set(xticks=[1,2,4],xlabel='Ready API replicas',ylabel=title,title=title,ylim=(0,None));ax.grid(alpha=.2)
        fig.suptitle('TC-23: sampled resource usage (fresh-pod metric windows)')
        save(fig,args.output/'tc23-resources',plt)
    if capacity:
        fig,axes=plt.subplots(1,2,figsize=(10,4),layout='constrained')
        for n in (1,2,4):
            group=sorted([r for r in capacity if r['replicas']==n],key=lambda r:r['rate'])
            for ax,key in zip(axes,('achieved_registration_rps','p95_ms')):
                ax.plot([r['rate'] for r in group],[r[key] for r in group],marker='o',label=f'{n} replicas')
                ax.set(xlabel='Scheduled arrivals/s');ax.grid(alpha=.2);ax.legend()
        bounds=[0,max(r['rate'] for r in capacity)]
        axes[0].plot(bounds,bounds,'--',color='gray',label='Offered rate')
        axes[0].set(ylabel='Accepted registrations/s',title='Capacity grid: actual throughput',ylim=(0,None),xlim=(0,None))
        axes[1].axhline(1000,ls='--',color='gray');axes[1].set(ylabel='P95 HTTP latency (ms)',title='Predeclared P95 SLO: 1,000 ms',ylim=(0,None),xlim=(0,None))
        for ax,key in zip(axes,('achieved_registration_rps','p95_ms')):
            for r in capacity:
                if not r['sustainable']:
                    ax.scatter(r['rate'],r[key],marker='x',color='#be4b35',s=65,zorder=4)
        save(fig,args.output/'tc23-capacity',plt)
        fig,axes=plt.subplots(1,3,figsize=(12,4),layout='constrained')
        for ax,app in zip(axes,('frontend','redis','postgres')):
            for n in (1,2,4):
                group=sorted([r for r in capacity if r['replicas']==n],key=lambda r:r['rate'])
                ax.plot([r['rate'] for r in group],[r[app+'_mean_cpu_millicores'] for r in group],
                    marker='o',label=f'{n} API replicas')
            ax.set(xlabel='Scheduled arrivals/s',ylabel='Mean CPU (millicores)',title=app,ylim=(0,None))
            ax.grid(alpha=.2);ax.legend(fontsize=8)
        fig.suptitle('TC-23: sampled shared-service CPU across the capacity grid')
        save(fig,args.output/'tc23-shared-resources',plt)
    surge=[r for r in records if r['profile']=='spike' and r['duration']==40]
    if surge:
        fig,axes=plt.subplots(1,2,figsize=(10,4),layout='constrained')
        labels=[Path(r['path']).parent.name for r in surge]
        axes[0].bar(labels,[r['accepted'] for r in surge],label='Accepted',color='#147d92')
        axes[0].axhline(2100,ls='--',color='gray',label='2,100 scheduled')
        axes[0].set(ylabel='Registrations',title='TC-19: complete original workload');axes[0].legend()
        axes[1].bar(labels,[r['max_launch_lag_seconds'] for r in surge],color='#24465e')
        axes[1].axhline(1,ls='--',color='#be4b35',label='Original 1-second limit')
        axes[1].set(ylabel='Maximum client launch lag (seconds)',title='Timing fidelity');axes[1].legend()
        save(fig,args.output/'tc19-surge',plt)
        fig,axes=plt.subplots(1,2,figsize=(10,4),layout='constrained')
        for index,r in enumerate(surge):
            folder=Path(r['path']).parent
            raw=json.loads((folder/'summary.json').read_text())
            rows=json.loads((folder/'arrivals.json').read_text())
            bins=[sum(int(p['launched_seconds'])==second for p in rows if 'launched_seconds' in p) for second in range(40)]
            axes[0].step(range(40),bins,where='post',alpha=.75,label=folder.name)
            for phase,shift,color in [('baseline',-.16,'#147d92'),('surge',.16,'#24465e')]:
                axes[1].bar(index+shift,raw['phases'][phase]['p95_ms'],width=.3,color=color,
                            label=phase if index==0 else None)
        axes[0].step([0,10,30,40],[5,100,5,5],where='post',ls='--',color='gray',label='Original schedule')
        axes[0].set(xlabel='Seconds since generator start',ylabel='Header-send callbacks / second',title='TC-19: delivered traffic')
        axes[0].legend(fontsize=8)
        axes[1].set(xticks=range(len(surge)),xticklabels=labels,ylabel='P95 HTTP latency (ms)',title='Baseline and surge phases')
        axes[1].legend()
        fig.suptitle('Client measurements; see run clock precision notes')
        save(fig,args.output/'tc19-traffic-latency',plt)
    lines=['# Actual study measurements','', 'Every row comes from a saved summary. Missing values remain unavailable. CPU/memory are sampled Kubernetes Metrics API observations; latency includes the gateway and port-forward.','',
        '| Trial | Status | Scheduled / launched / accepted | Drops | Upstream retries / known | Max lag s | P95 ms | Accepted/s | SQL violations |',
        '|---|---|---|---|---|---|---|---|---|']
    def number(v):return 'unavailable' if v is None else f'{v:.3f}' if isinstance(v,float) else str(v)
    for r in records:
        lines.append('| '+' | '.join([r['run']+'/'+Path(r['path']).parent.name,r['status'],
            ' / '.join(number(r[k]) for k in ('scheduled','launched','accepted')),number(r['generator_dropped']),
            ' / '.join(number(r[k]) for k in ('upstream_retries','upstream_attempts_known')),
            number(r['max_launch_lag_seconds']),number(r['p95_ms']),number(r['achieved_registration_rps']),number(r['sql_violations'])])+' |')
    (args.output/'measurements.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def save(fig,path,plt):
    fig.savefig(str(path)+'.png',bbox_inches='tight',dpi=300)
    fig.savefig(str(path)+'.svg',bbox_inches='tight')
    plt.close(fig)


def hpa_plot(run,output,plt):
    samples=json.loads((run/'timeline.json').read_text())
    phases=json.loads((run/'phases.json').read_text())
    if not samples:return
    target=json.loads((run/'hpa-config.json').read_text())['metadata']['name']
    start=samples[0]['monotonic']
    xs=[];ready=[];desired=[];cpu=[];cpu_target=[]
    for s in samples:
        xs.append((s['monotonic']-start)/60)
        d=next((d for d in s.get('deployments',{}).get('items',[]) if d['metadata']['name']==target),{})
        ready.append(d.get('status',{}).get('readyReplicas',0) if d else float('nan'))
        request_cpu=sum(quantity(c.get('resources',{}).get('requests',{}).get('cpu','0'))*1000
                        for c in d.get('spec',{}).get('template',{}).get('spec',{}).get('containers',[]))
        cpu_target.append(request_cpu*.5*ready[-1])
        h=next((h for h in s.get('hpa',{}).get('items',[]) if h['metadata']['name']==target),{})
        desired.append(h.get('status',{}).get('desiredReplicas',float('nan')))
        pods={p['metadata']['name'] for p in s.get('pods',{}).get('items',[]) if p['metadata'].get('labels',{}).get('app')==target}
        metrics=[p for p in s.get('metrics',{}).get('items',[]) if p['metadata']['name'] in pods]
        cpu.append(sum(quantity(c['usage']['cpu'])*1000 for p in metrics for c in p['containers']) if metrics else float('nan'))
    is_worker=target=='allocation-worker'
    fig,axes=plt.subplots(4 if is_worker else 3,1,figsize=(10,10 if is_worker else 8),sharex=True,layout='constrained')
    axes[0].step(xs,ready,where='post',label='Actual Ready')
    axes[0].step(xs,desired,where='post',ls='--',label='HPA desired')
    axes[0].set(ylabel='Replicas',yticks=[0,1,2,3,4],title='TC-24: '+target+' ('+run.name+')');axes[0].legend()
    axes[1].plot(xs,cpu,color='#147d92',label='Observed target workload CPU')
    axes[1].step(xs,cpu_target,where='post',ls='--',color='gray',label='50% of Ready pods\' CPU requests')
    axes[1].set(ylabel='Total target CPU (millicores)');axes[1].legend(fontsize=8)
    traffic={}
    for name,p in phases.items():
        arrival_file=run/name/'arrivals.json'
        if not arrival_file.exists():continue
        for r in json.loads(arrival_file.read_text()):
            if 'launched_seconds' in r:
                second=int((datetime.fromisoformat(r['sent_at'])-datetime.fromisoformat(samples[0]['at'])).total_seconds()) if r.get('sent_at') else int(p['monotonic']+r['launched_seconds']-start)
                traffic[second//5*5]=traffic.get(second//5*5,0)+1
    bins=list(range(0,int(samples[-1]['monotonic']-start)+5,5))
    axes[2].step([b/60 for b in bins],[traffic.get(b,0)/5 for b in bins],where='post',color='#24465e')
    axes[2].set(ylabel='Header-send callbacks/s')
    if is_worker:
        axes[3].plot(xs,[s.get('waiting_queue',{}).get('queued_count',float('nan')) for s in samples],color='#be4b35',label='Waiting-room QUEUED')
        axes[3].plot(xs,[sum(s['backlog'].get(state,0) for state in ('QUEUED','IN_PROGRESS','RETRY','BLOCKED'))
                        if 'backlog' in s else float('nan') for s in samples],color='#147d92',label='Unfinished allocation jobs')
        axes[3].set(ylabel='Parties / jobs');axes[3].legend(fontsize=8)
    axes[-1].set_xlabel('Minutes since monitoring began')
    for ax in axes:
        ax.grid(alpha=.2)
        for name,p in phases.items():
            x=(p['monotonic']-start)/60
            ax.axvline(x,color='gray',alpha=.4,ls=':')
            if ax==axes[0]:ax.annotate(name,(x,.98),xycoords=('data','axes fraction'),va='top',fontsize=8,
                                      bbox=dict(facecolor='white',edgecolor='none',alpha=.7))
    save(fig,output/('tc24-'+target),plt)


if __name__=='__main__':main()
