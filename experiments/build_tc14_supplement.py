"""Render the TC-14 supplement from an exported cohort. Requires reportlab and pypdf."""

import argparse
from functools import partial
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.platypus import Image, PageBreak, SimpleDocTemplate, Spacer

from build_instructions import INK, MUTED, WIDTH, make_table, paragraph
from control import read


def footer(canvas, document, page_offset=0):
    width, height = A4
    canvas.setStrokeColor(INK)
    canvas.line(42, height - 32, width - 42, height - 32)
    canvas.setFillColor(MUTED)
    canvas.setFont('Helvetica', 8)
    canvas.drawString(42, height - 44, 'CSC3104 / GROUP 02 / PERFORMANCE SUPPLEMENT')
    canvas.drawRightString(width - 42, 28, str(page_offset + document.page))


def build(evidence, output, *, page_offset=0):
    experiment = read(evidence / 'experiment.json')
    summary = read(evidence / 'summary.json')
    rows = [*summary['per_trial'], summary['aggregate']]
    fields = ('mean_ms', 'median_ms', 'p95_ms', 'p99_ms', 'stdev_ms', 'min_ms', 'max_ms')
    table = ['| Trial | Success | Failed | SQL | Mean | Median | P95 | P99 | SD | Min | Max |']
    for row in rows:
        timings = [f'{row[key]:.2f}' if row[key] is not None else '-' for key in fields]
        values = [row[key] if row[key] is not None else '-' for key in
                  ('trial', 'successful', 'failed', 'invariant_violations')]
        table.append('| ' + ' | '.join(map(str, [*values, *timings])) + ' |')
    pooled = summary['aggregate']
    title = ('Appendix B. TC-14 extended seat reservation baseline' if page_offset
             else 'TC-14 extended seat reservation baseline')
    story = [paragraph(title, 'h1'),
             paragraph(f"{experiment['run_id']}  /  {pooled['status']}", 'h3'),
             paragraph(f"{pooled['successful']}/{pooled['planned']} measured holds succeeded. "
                       f"{pooled['warmup_attempted']} warm-up attempts were recorded separately. "
                       f"{pooled['missing']} planned measurements were missing."),
             paragraph('Measurements by trial', 'h2'),
             make_table(table), Spacer(1, 10),
             paragraph('Latency columns are in ms and use only successful measured holds. SD is sample standard deviation. '
                       'Percentiles are linearly interpolated. SQL counts are from the final invariant audit in each trial. '
                       'The All trials row pools requests.'),
             paragraph('Experimental protocol', 'h2'),
             paragraph('Five fresh Kind namespaces ran the same images, one Ready pod per component, a 300-second '
                       'hold TTL and batch size 10. Each started with 200 available Section C seats. Ten one-seat '
                       'warm-up holds preceded 100 measurements at client concurrency one. Every attempt used a fresh '
                       'connection and a unique request ID.'),
             paragraph('The client timed each POST /seats/hold through the loopback Kubernetes port-forward to '
                       'seat-api, through complete response-body receipt. This includes the hold transaction. '
                       'End-to-end booking also includes frontend, waiting-room admission, batching, allocation and payment.'),
             paragraph('Reproduce and verify', 'h2'),
             paragraph('Start the project Kind cluster with its images loaded. Run from the repository root with '
                       'Python 3.10+ and Matplotlib for the exporter. Use a new run ID and output path.'),
             paragraph('python experiments/tc14_extended.py --run tc14-repro01', 'code'),
             paragraph('python experiments/tc14_report.py --run tc14-repro01 --output output/tc14-repro01', 'code'),
             paragraph(f'Review raw-observations.csv, summary.json and trial directories in {evidence.name}. '
                       'See docs/TC14_EXTENDED_RESULTS.md for environment, outcome definitions and interpretation.'),
             PageBreak(), paragraph('Distribution and trial variation', 'h1')]
    for name in ('latency-distribution.png', 'latency-boxplot.png'):
        image = Image(str(evidence / name), width=WIDTH * 0.96, height=WIDTH * 0.48)
        story.extend([image, Spacer(1, 10)])
    story.append(paragraph('Use these figures as a baseline for direct holds on this local deployment. The first-fit '
                           'inventory shrinks from 190 available seats at the start of measurement to 90 after a fully '
                           'successful trial. The five trials share a host, so the figures describe local variation. '
                           'The historical TC-14 observations used a frontend proxy and a ten-seat section.'))
    target = str(output) if isinstance(output, Path) else output
    doc = SimpleDocTemplate(target, pagesize=A4, title='CSC3104 Group 02 - TC-14 extended',
                            author='CSC3104 Group 02', leftMargin=36, rightMargin=36, topMargin=62, bottomMargin=45)
    decorate = partial(footer, page_offset=page_offset)
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    build(args.evidence, args.output)
