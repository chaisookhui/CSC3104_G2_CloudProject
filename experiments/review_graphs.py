"""Export TC16/18 plots and CSV from complete saved final-v9 measurements.

No deployments or new workloads. TC23/24 graphs already exist in report-v9.
"""
import csv
import json
import os
from pathlib import Path
import statistics

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/review-package/graphs'


def main():
    os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'.local/matplotlib'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'figure.dpi':160})
    OUT.mkdir(parents=True,exist_ok=True)
    rows=[]
    for workers in (1,2,4):
        run=f'tc-fix-regression-v9-TC16-{workers}'
        data=json.loads((ROOT/'.local/test-results'/run/'comparison.json').read_text())
        assert data['status']=='PASS' and len(data['results'])==6 and data['identical_initial_inventory']
        for entry in data['results']:
            r=entry['result'];assert r['status']=='PASS' and r['customers']==40 and r['invariants']['violations']==0
            rows.append(dict(run=run,workers=workers,seed=entry['seed'],repeat=entry['repeat'],policy=entry['policy'],
                             confirmed_parties=r['confirmations'],reserved_parties=r['reservations'],
                             elapsed_seconds=r['elapsed_seconds'],confirmed_parties_per_second=r['confirmations']/r['elapsed_seconds'],
                             confirmed_seats=r['confirmed_trace_seats'],inventory_seats=r['total_inventory'],
                             sql_violations=r['invariants']['violations']))
    def csvfile(name,values):
        with (OUT/name).open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=list(values[0]));w.writeheader();w.writerows(values)
    csvfile('tc16-trials.csv',rows)
    colors={'demand-cycle':'#167c91','fcfs':'#cb7541'}
    def finish(fig,name):
        fig.tight_layout();fig.savefig(OUT/(name+'.png'),bbox_inches='tight');fig.savefig(OUT/(name+'.svg'),bbox_inches='tight');plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(11,4.6))
    for policy in colors:
        groups=[[r for r in rows if r['policy']==policy and r['workers']==n] for n in (1,2,4)]
        for ax,key in zip(axes,('confirmed_parties_per_second','elapsed_seconds')):
            for n,g in zip((1,2,4),groups):
                ax.scatter([n+(-.035 if policy=='demand-cycle' else .035)]*len(g),[r[key] for r in g],color=colors[policy],alpha=.65,s=30)
            ax.plot([1,2,4],[statistics.mean(r[key] for r in g) for g in groups],color=colors[policy],marker='o',label=policy+' mean (3 trials)')
    axes[0].set(title='TC-16: actual confirmed-party goodput',ylabel='Confirmed parties / replay second')
    axes[1].set(title='TC-16: complete replay time',ylabel='Elapsed seconds')
    for ax in axes:ax.set(xlabel='Ready allocation workers',xticks=[1,2,4]);ax.grid(alpha=.2);ax.legend(fontsize=8)
    fig.suptitle('F1, 40 parties, seed 42, batch 10, TTL 120s; both policies reset to matching inventory',fontsize=10)
    finish(fig,'tc16-worker-scaling')
    data=json.loads((ROOT/'.local/test-results/tc-fix-regression-v9-TC18/comparison.json').read_text())
    assert data['status']=='PASS' and len(data['results'])==20 and data['fairness']['independent_seeds']==10
    policies=[];sections=[];groups=[]
    for entry in data['results']:
        r=entry['result'];assert r['status']=='PASS' and r['customers']==40
        common=dict(seed=entry['seed'],repeat=entry['repeat'],policy=entry['policy'])
        policies.append(dict(**common,reserved_parties=r['reservations'],confirmed_parties=r['confirmations'],
                             confirmed_seats=r['confirmed_trace_seats'],inventory_seats=r['total_inventory'],
                             seat_utilization_percent=100*r['incremental_venue_utilization'],
                             elapsed_seconds=r['elapsed_seconds'],overtakes=r['overtakes']))
        for section in r['fairness']['sections']:sections.append(dict(**common,**section))
        for group in r['groups']:groups.append(dict(**common,**group))
    csvfile('tc18-policy-seeds.csv',policies);csvfile('tc18-section-fairness.csv',sections);csvfile('tc18-group-measurements.csv',groups)
    csvfile('tc18-paired-section-differences.csv',data['fairness']['pairs'])
    fig,axes=plt.subplots(1,2,figsize=(11,4.6))
    for ax,key,label in [(axes[0],'reservation_rate_gap','Reservation-rate gap (percentage points)'),(axes[1],'jain_reservation_rates',"Jain index of size-specific reservation rates")]:
        for policy in colors:
            means=[]
            for x,section in enumerate('ABCD'):
                selected=[r for r in sections if r['section']==section and r['policy']==policy and r['interpretable']]
                assert len(selected)==10 and all(r[key] is not None for r in selected)
                values=[r[key]*(100 if key=='reservation_rate_gap' else 1) for r in selected]
                means.append(statistics.mean(values));offset=-.06 if policy=='demand-cycle' else .06
                ax.scatter([x+offset]*len(values),values,color=colors[policy],alpha=.4,s=22)
            ax.plot(range(4),means,marker='o',color=colors[policy],label=policy+' mean (10 seeds)')
        ax.set(xlabel='Section',ylabel=label,xticks=range(4),xticklabels=list('ABCD'));ax.grid(alpha=.2);ax.legend(fontsize=8)
    axes[0].set_title('TC-18: smaller gap = more equal rates');axes[1].set_title('TC-18: nearer 1 = more equal rates')
    fig.suptitle('F1 paired seeds 42-51, one worker; descriptive observations, no superiority assumption',fontsize=10)
    finish(fig,'tc18-fairness-by-section')
    fig,axes=plt.subplots(1,3,figsize=(12,4.3))
    for ax,key,title in zip(axes,('confirmed_parties','seat_utilization_percent','overtakes'),('Confirmed parties / 40','Confirmed seat utilization (%)','Observed FCFS overtakes')):
        for seed in range(42,52):
            pair=[next(r for r in policies if r['seed']==seed and r['policy']==p) for p in ('demand-cycle','fcfs')]
            ax.plot([0,1],[r[key] for r in pair],color='#8796a5',alpha=.35,linewidth=.8)
        for x,policy in enumerate(colors):
            values=[r[key] for r in policies if r['policy']==policy];ax.scatter([x]*len(values),values,color=colors[policy],alpha=.7,s=28)
            ax.scatter([x],[statistics.mean(values)],marker='_',s=400,color='#192b41',zorder=5)
        ax.set(title=title,xticks=[0,1],xticklabels=['Demand-Cycle','FCFS']);ax.grid(axis='y',alpha=.2)
    fig.suptitle('TC-18: each faint line joins the same seed; dark bars are means (10 seeds/policy)',fontsize=10)
    finish(fig,'tc18-policy-tradeoffs')
    notes=dict(status='PASS',source_runs=['tc-fix-regression-v9-TC16-'+str(n) for n in (1,2,4)]+['tc-fix-regression-v9-TC18'],
               tc16_trials=len(rows),tc18_policy_replays=len(policies),tc18_section_observations=len(sections),
               tc18_paired_sections=len(data['fairness']['pairs']),
               definitions=['Goodput=confirmed parties / full replay elapsed_seconds, not seat-store RPS.',
                            'Utilization=incremental_venue_utilization from saved summaries x100; denominator=70-seat inventory in these fresh F1 trials.',
                            'Fairness gaps compare party-size reservation rates within each section; smaller gaps and larger Jain indices imply more equal measured rates.',
                            'Dots are individual recorded trials/seeds; lines are descriptive means or paired observations, not fitted speedups or confidence intervals.',
                            'TC18 F1 seeds42-51 only; optional F2-F7 scenarios are not inferred.'])
    (OUT/'tc16-tc18-measurements.json').write_text(json.dumps(notes,indent=2),encoding='utf-8')
    print(json.dumps(notes,indent=2))


if __name__=='__main__':main()
