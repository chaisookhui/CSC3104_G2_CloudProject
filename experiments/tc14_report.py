"""Export TC-14 extended evidence and plot saved observations without running the app."""

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import shutil
from statistics import mean, median, stdev

from control import read
from runtime import RESULTS, write_json
from workloads import percentile, write_rows


def successful_latencies(rows):
    return [row['latency_ms'] for row in rows
            if row['phase'] == 'measured' and row['outcome'] == 'RESERVED']


def summarize(label, status, rows, planned, checks):
    measured = Counter(row['outcome'] for row in rows if row['phase'] == 'measured')
    warmup = Counter(row['outcome'] for row in rows if row['phase'] == 'warmup')
    values = successful_latencies(rows)
    return dict(trial=label, status=status, planned=planned, attempted=measured.total(),
                missing=planned - measured.total(), successful=len(values),
                failed=measured.total() - len(values),
                failure_outcomes={k: v for k, v in measured.items() if k != 'RESERVED'},
                warmup_attempted=warmup.total(), warmup_successful=warmup['RESERVED'],
                warmup_failed=warmup.total() - warmup['RESERVED'],
                invariant_violations=sum(checks) if all(n is not None for n in checks) else None,
                mean_ms=mean(values) if values else None, median_ms=median(values) if values else None,
                p95_ms=percentile(values, 95), p99_ms=percentile(values, 99),
                stdev_ms=stdev(values) if len(values) > 1 else None,
                min_ms=min(values) if values else None, max_ms=max(values) if values else None)


def plots(directory, by_trial, pooled, status):
    from matplotlib import use
    use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator, PercentFormatter, ScalarFormatter

    values = sorted(value for trial in by_trial for value in trial)
    if not values:
        return
    log_scale = max(values) / min(values) >= 10
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 11,
                         'axes.spines.top': False, 'axes.spines.right': False,
                         'axes.labelcolor': '#26384a', 'text.color': '#142b42'})
    samples_label = f'{len(values)} successful measured requests across {len(by_trial)} planned trials'
    if status != 'PASS':
        samples_label += '  |  Provisional evidence'

    fig, ax = plt.subplots(figsize=(8.2, 4.1), layout='constrained')
    ax.step([values[0], *values], [0, *(i / len(values) for i in range(1, len(values) + 1))],
            where='post', linewidth=2.2, color='#126e82')
    for key, name, color in [('median_ms', 'Median', '#126e82'), ('p95_ms', 'P95', '#996018'),
                             ('p99_ms', 'P99', '#9e3961')]:
        value = pooled[key]
        ax.axvline(value, color=color, linestyle='--', alpha=0.85, label=f'{name} {value:.2f} ms')
    if log_scale:
        ax.set_xscale('log')
        ax.xaxis.set_major_formatter(ScalarFormatter())
    else:
        ax.xaxis.set_major_locator(MaxNLocator(nbins=8))
    ax.set(xlabel='Request latency (ms)' + (' · log scale' if log_scale else ''),
           ylabel='Share at or below latency', ylim=(0, 1.025))
    ax.yaxis.set_major_formatter(PercentFormatter(1))
    ax.grid(axis='y', color='#dce4eb')
    ax.legend(loc='lower right', frameon=False)
    ax.set_title('Seat reservation latency distribution\n' + samples_label, loc='left', pad=12)
    fig.savefig(directory / 'latency-distribution.png', dpi=200, facecolor='white')
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8.2, 4.1), layout='constrained')
    ax.boxplot(by_trial, whis=1.5, widths=.44, patch_artist=True,
               boxprops={'facecolor': '#d0e8e9', 'edgecolor': '#126e82'},
               medianprops={'color': '#142b42', 'linewidth': 2},
               whiskerprops={'color': '#126e82'}, capprops={'color': '#126e82'},
               flierprops={'marker': 'o', 'markersize': 3.7, 'markeredgecolor': '#9e3961', 'alpha': .8})
    ax.set_xticks(range(1, len(by_trial) + 1),
                  [f'Trial {i}\nn = {len(trial)}' for i, trial in enumerate(by_trial, 1)])
    if log_scale:
        ax.set_yscale('log')
        ax.yaxis.set_major_formatter(ScalarFormatter())
    else:
        ax.yaxis.set_major_locator(MaxNLocator(nbins=7))
    ax.set_ylabel('Request latency (ms)' + (' · log scale' if log_scale else ''))
    ax.grid(axis='y', color='#dce4eb')
    ax.set_axisbelow(True)
    ax.set_title('Seat reservation latency by trial\nBoxes show the middle 50% · Whiskers extend to 1.5 × IQR · Dots show outliers',
                 loc='left', pad=12)
    fig.savefig(directory / 'latency-boxplot.png', dpi=200, facecolor='white')
    plt.close(fig)


def export(source, output):
    experiment = read(source / 'experiment.json')
    if experiment['case'] != 'TC-14 extended' or 'finished_at' not in experiment:
        raise ValueError('Choose a finished TC-14 extended run')
    protocol = experiment['protocol']
    planned = protocol['measured_per_trial']
    summaries, by_trial, checks, all_rows = [], [], [], []
    for number in range(1, protocol['trials'] + 1):
        child = source / f'trial-{number}'
        record = read(child / 'trial.json') if (child / 'trial.json').exists() else {}
        journal = child / 'observations.jsonl'
        rows = [json.loads(line) for line in journal.read_text(encoding='utf-8').splitlines()] if journal.exists() else []
        expected = [(phase, index) for phase, count in [('warmup', protocol['warmup_per_trial']),
                    ('measured', planned)] for index in range(1, count + 1)]
        if ([(r['phase'], r['index']) for r in rows] != expected[:len(rows)] or
                any(r['trial'] != number or r['latency_ms'] <= 0 for r in rows)):
            raise ValueError(f'Trial {number} observations do not match the sequential protocol')
        outcome = record.get('status', 'NOT_RUN')
        after = record.get('sql_after', {}).get('violations')
        if outcome == 'PASS' and (len(rows) != len(expected) or after != 0 or
                not all(r['outcome'] == 'RESERVED' for r in rows)):
            raise ValueError(f'Trial {number} PASS conflicts with its recorded evidence')
        summaries.append(summarize(number, outcome, rows, planned, [after]))
        by_trial.append(successful_latencies(rows))
        checks.append(after)
        all_rows.extend(rows)
    if len({row['request_id'] for row in all_rows}) != len(all_rows):
        raise ValueError('Raw observation request IDs are not unique')
    raw = source / 'raw-observations.json'
    if raw.exists() and read(raw) != all_rows:
        print('Combined raw snapshot differs from the append-only journals. Exporting from the journals.')
    pooled = summarize('All trials', experiment['status'], all_rows, planned * len(summaries), checks)
    if experiment['status'] == 'PASS' and any(r['status'] != 'PASS' for r in summaries):
        raise ValueError('The run PASS conflicts with the trial records')
    output.mkdir(parents=True, exist_ok=False)
    shutil.copy2(source / 'experiment.json', output)
    for child in sorted(source.glob('trial-*')):
        target = output / child.name
        target.mkdir()
        for path in sorted(child.glob('*.json')):
            shutil.copy2(path, target)
    write_rows(output, all_rows, 'raw-observations')
    write_json(output / 'summary.json', {'per_trial': summaries, 'aggregate': pooled})
    with (output / 'summary.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=pooled.keys())
        writer.writeheader()
        for row in [*summaries, pooled]:
            writer.writerow({**row, 'failure_outcomes': json.dumps(row['failure_outcomes'])})
    plots(output, by_trial, pooled, experiment['status'])
    print(json.dumps(pooled, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, help='Saved run ID under .local/test-results')
    parser.add_argument('--output', type=Path, required=True, help='New evidence export directory')
    args = parser.parse_args()
    if Path(args.run).name != args.run or args.run in ('.', '..'):
        parser.error('Provide a saved run ID, without a path')
    export(RESULTS / args.run, args.output)


if __name__ == '__main__':
    main()
