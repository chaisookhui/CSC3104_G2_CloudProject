"""Descriptive fairness measures. Unknown outcomes prevent a fairness conclusion."""
from collections import defaultdict
from statistics import mean


def fairness_summary(groups):
    sections=defaultdict(list)
    for group in groups:
        sections[group['section']].append(group)
    result=[]
    for section, values in sorted(sections.items()):
        rates=[g['reservation_rate'] for g in values]
        total=sum(rates)
        unknown=sum(g['unknown'] for g in values)
        # Equal weight per offered party-size stratum, conditional on section.
        # A zero-service population has no fairness score, rather than perfect fairness.
        jain=total**2/(len(rates)*sum(r*r for r in rates)) if total else None
        result.append(dict(section=section, represented_sizes=sorted(g['party_size'] for g in values),
            reservation_rate_gap=max(rates)-min(rates), jain_reservation_rates=jain,
            unknown_customers=unknown, complete_size_coverage=len(values)==4,
            interpretable=not unknown and len(values)==4 and total>0))
    return dict(objective='Equal opportunity to reserve a whole party across sizes 1-4 within each section; '
                'evaluate reservation-rate gaps alongside decision waits, FCFS overtakes and seat utilization. '
                'Capacity and adjacency can make equal rates infeasible; no policy is assumed superior.',
                sections=result)


def paired_analysis(results):
    pairs=defaultdict(dict)
    for entry in results:
        pairs[(entry.get('seed'),entry['repeat'])][entry['policy']]=entry['result']
    deltas=[]
    for (seed, repeat), pair in pairs.items():
        if set(pair)!={'demand-cycle','fcfs'}: continue
        demand,fcfs=pair['demand-cycle'],pair['fcfs']
        if demand['status']!='PASS' or fcfs['status']!='PASS': continue
        if demand['initial_fingerprint']!=fcfs['initial_fingerprint']: continue
        for left in demand['fairness']['sections']:
            right=next((s for s in fcfs['fairness']['sections'] if s['section']==left['section']),None)
            if not right or not left['interpretable'] or not right['interpretable']: continue
            deltas.append(dict(seed=seed,repeat=repeat,section=left['section'],
                reservation_gap_delta=left['reservation_rate_gap']-right['reservation_rate_gap'],
                jain_delta=left['jain_reservation_rates']-right['jain_reservation_rates']))
    return dict(pairs=deltas, mean_gap_delta=mean(d['reservation_gap_delta'] for d in deltas) if deltas else None,
                independent_seeds=len({d['seed'] for d in deltas}),
                interpretation='Negative gap delta favours Demand-Cycle on rate equality. Positive Jain delta favours it. '
                'These are descriptive paired effects, not statistical significance; repeated seeds are not independent samples.')


def write_report(directory,results):
    """A readable evidence report for the assessor, using only recorded results."""
    analysis=paired_analysis(results)
    def number(value):return 'unavailable' if value is None else f'{value:.3f}'
    lines=['# Recorded policy comparison','',
        'Objective: equal opportunity to reserve a complete party across sizes 1-4 within each section.',
        'Read rate equality alongside waits, overtakes and utilization. No policy is assumed superior.','',
        '| Seed / repeat | Policy | Status | Confirmations | Overtakes | Incremental venue utilization |',
        '|---|---|---|---|---|---|']
    for entry in results:
        r=entry['result']
        lines.append(f"| {entry.get('seed')} / {entry['repeat']} | {entry['policy']} | {r['status']} | {r['confirmations']} | {r['overtakes']} | {number(r['incremental_venue_utilization'])} |")
    lines+=['','| Seed / repeat | Policy | Section | Rate gap | Jain index | Interpretable |',
            '|---|---|---|---|---|---|']
    for entry in results:
        for section in entry['result']['fairness']['sections']:
            lines.append(f"| {entry.get('seed')} / {entry['repeat']} | {entry['policy']} | {section['section']} | {number(section['reservation_rate_gap'])} | {number(section['jain_reservation_rates'])} | {section['interpretable']} |")
    lines+=['',f"Independent seeds with interpretable paired sections: {analysis['independent_seeds']}.",
        f"Mean paired reservation-gap difference (Demand-Cycle minus FCFS): {number(analysis['mean_gap_delta'])}.",
        analysis['interpretation'],'',
        'Inspect per-policy customers.csv and summary.json for group sample sizes, reservation/confirmation rates, median/P95 waits, unknown outcomes and physical inventory. '
        'A small gap can coexist with low service; zero-service groups receive no Jain score. '
        'This report provides descriptive evidence and does not establish statistical significance.']
    (directory/'fairness.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
