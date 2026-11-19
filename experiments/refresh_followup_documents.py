"""Append the audited 19-Nov follow-up to current submission documents.

Offline only. Preserves the existing 22-page report as the baseline, appends a
four-page supplement, and rebuilds instructions from its edited Markdown source.
Never invokes the historical builder that also recreates the deleted combined PDF.
The sealed test-evidence ZIP is not changed. Requires reportlab and pypdf.
"""
from html import escape
from io import BytesIO
import hashlib
import json
from pathlib import Path
import re

from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.pdfgen import canvas

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/pdf'
EVIDENCE=ROOT/'output/validation/followup-20261119'
REPORT=EVIDENCE/'report'
REFRESH=EVIDENCE/'document-refresh'
STEM='GROUP02_Test_Results_and_Distributed_Concepts_Report'
MARK='followup-20261119'
INK=colors.HexColor('#1B2A41')
TEAL=colors.HexColor('#15656D')
BODY=ParagraphStyle('followup-body',fontName='Helvetica',fontSize=9.2,leading=12,spaceAfter=7,textColor=INK)
SMALL=ParagraphStyle('followup-small',parent=BODY,fontSize=8,leading=10,spaceAfter=6)
HEADING=ParagraphStyle('followup-heading',parent=BODY,fontName='Helvetica-Bold',fontSize=18,leading=22,spaceAfter=10)
SUB=ParagraphStyle('followup-sub',parent=BODY,fontName='Helvetica-Bold',fontSize=11,leading=14,textColor=TEAL,spaceBefore=5)
CELL=ParagraphStyle('followup-cell',parent=SMALL,spaceAfter=0)
HEAD=ParagraphStyle('followup-head',parent=CELL,fontName='Helvetica-Bold',textColor=colors.white)


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ascii_text(text):
    for a,b in {'\u2013':'-','\u2014':'-','\u2212':'-','\u2011':'-',
                '\u2264':'<=','\u2265':'>=','\u0394':'Delta','\u00d7':'x','\u2192':'->'}.items():
        text=text.replace(a,b)
    return text


def p(text,style=BODY):return Paragraph(escape(ascii_text(str(text))),style)


def block(path,key,body,prefix=False):
    start=f'<!-- {MARK}:{key}:start -->';end=f'<!-- {MARK}:{key}:end -->'
    value=f'{start}\n{body.strip()}\n{end}'
    text=path.read_text(encoding='utf-8-sig')
    if start in text:
        text=re.sub(re.escape(start)+r'.*?'+re.escape(end),lambda m:value,text,flags=re.S)
    elif prefix:
        first,separator,rest=text.partition('\n')
        text=first+'\n\n'+value+'\n'+rest
    else:text=text.rstrip()+'\n\n'+value+'\n'
    path.write_text(text,encoding='utf-8',newline='\n')


def table(rows,width=511,widths=None):
    n=len(rows[0]);widths=widths or [width/n]*n
    result=Table([[p(cell,HEAD if i==0 else CELL) for cell in row] for i,row in enumerate(rows)],
                 colWidths=widths,repeatRows=1,hAlign='LEFT')
    result.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),INK),('VALIGN',(0,0),(-1,-1),'TOP'),
        ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),
        ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5),
        ('LINEBELOW',(0,0),(-1,0),.6,TEAL),('LINEBELOW',(0,1),(-1,-1),.3,colors.HexColor('#D9E0E7')),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#F3F6F9')])]))
    return result


def page_pdf(items,number,size=A4):
    output=BytesIO()
    def header(c,doc):
        w,h=size;c.setStrokeColor(INK);c.line(42,h-29,w-42,h-29)
        c.setFillColor(colors.HexColor('#566477'));c.setFont('Helvetica',7.3)
        c.drawString(42,h-42,'CSC3104 / GROUP 02 / FOLLOW-UP EVIDENCE / 19 NOV 2026')
        c.drawString(42,22,'Measured local Kind results. Original baseline and unsuccessful attempts retained.')
        c.drawRightString(w-42,22,str(number+doc.page-1))
    doc=SimpleDocTemplate(output,pagesize=size,leftMargin=42,rightMargin=42,topMargin=60,bottomMargin=48)
    doc.build(items,onFirstPage=header,onLaterPages=header)
    output.seek(0);reader=PdfReader(output)
    if len(reader.pages)!=1:raise ValueError(f'Supplement page {number} overflowed to {len(reader.pages)} pages')
    return reader


def figure(name,width,height):
    image=Image(str(REPORT/name));image._restrictSize(width,height);return image


def report_supplement(capacity,bursts,scheduler,baseline_count):
    pages=[]
    items=[p('Appendix A - Latest measured follow-up',HEADING),
        p('19 November 2026 (Singapore). All 64 planned units are COMPLETE: 30 scheduler pairs, four HPA cycles, 21 capacity trials and nine bursts. COMPLETE does not mean every performance threshold passed. The original 25-case baseline is preserved on the preceding pages.'),
        p('API capacity - unchanged composite SLO',SUB),
        p('Each trial used 30s constant offers, fresh equivalent lab state and HPA off. Passing requires P95 <=1,000ms, achieved rate >=95% of offer, zero HTTP failures, valid delivery, correct IDs/SQL and all requested replicas serving.')]
    rows=[['API replicas','Highest observed pass','Passing / valid trials at that rate','First observed miss (misses / valid)']]
    for r in capacity:rows.append([r['replicas'],f"{r['highest_passing_tested_rate']}/s",f"{r['passing_trials_at_highest']} / {r['trials_at_highest']}",f"{r['first_valid_miss_rate']}/s ({r['slo_miss_trials_at_first_miss']} / {r['trials_at_first_miss']})"])
    items+=[table(rows),Spacer(1,8),p('These are observed maxima, not stable capacity estimates. Of 21 trials, 19 had valid delivery; eight met the composite SLO. Two invalid attempts are excluded from capacity inference. At 250/s with one replica, only two of three attempts had valid delivery. All five complete 300/s attempts remain INCONCLUSIVE with unavailable accepted-ID reconciliation.'),
        p('Burst admission - original 600s deadline',SUB)]
    rows=[['Peak','Offers / trial','Passing / complete trials','Maximum admission']]
    for r in bursts:rows.append([f"{r['peak']}/s",r['planned_offers'],f"{r['passing_trials']} / {r['complete_trials']}",f"{r['max_admission_seconds']:.1f}s"])
    items+=[table(rows),Spacer(1,8),p('All 27,900 offers were accepted across the nine bursts. Unique IDs, stable contiguous queue positions, terminal outcomes and SQL checks passed. Terminal admission includes unavailable/expired outcomes; it does not mean thousands of successful bookings.'),
        p('Validation: 1,046 saved-data audit checks passed, zero failures. No planned trial remains pending. Historical interrupted attempts retain their status.',SMALL),
        p('Detailed evidence: docs/FOLLOWUP_EVALUATION_RESULTS.md and output/validation/followup-20261119/report/. Each CSV records raw run/trial paths.',SMALL)]
    pages.append(page_pdf(items,baseline_count+1))
    items=[p('Paired scheduler comparisons - TC-18',HEADING),figure('scheduler-paired-comparison.png',511,190),Spacer(1,8)]
    rows=[['Scenario','Delta parties','Delta seats','Delta Jain','Delta gap','Jain seed / section pairs']]
    for r in scheduler:
        if r['scenario']=='F1':continue
        rows.append([r['scenario'],f"{r['confirmed_parties_delta']:+.1f}",f"{r['confirmed_seats_delta']:+.1f}",f"{r['jain_delta']:+.6f}",f"{r['gap_delta']:+.4f}",f"{r['jain_seed_denominator']} / {r['jain_section_denominator']}"])
    items+=[table(rows,widths=[52,69,62,78,73,177]),Spacer(1,9),
        p('Each scenario used ten matched seeds 42-51, 40 parties, batch 10, one allocation worker and 120s holds. All 60 policy replays passed correctness checks. Deltas are Demand-Cycle minus FCFS within seed. Original F1 is a separate retained baseline.'),
        p('The original F1 parties-versus-Jain trade-off did not recur on mean paired effects. F3 nevertheless has a worse rate gap despite higher Jain, so there is no unqualified fairness-superiority claim. F6 fixture bookings are excluded from customer outcomes. Unrepresented sizes remain missing; Jain requires all four sizes, known outcomes and positive service.'),
        p('Per-policy counts, section/size reservation rates and denominators, median/P95 decision waits, utilization and metric-specific matched-pair counts are in scheduler-policies.csv, scheduler-strata.csv, scheduler-seed-deltas.csv and scheduler-section-pairs.csv.',SMALL),
        p('Article-ready material: report/ARTICLE_TABLE.md and report/ARTICLE_EVALUATION.md under the follow-up evidence root. Figures have editable SVG companions.',SMALL)]
    pages.append(page_pdf(items,baseline_count+2))
    items=[p('Four fresh CPU-based HPA cycles - TC-24',HEADING),
        figure('hpa-fresh-overview.png',758,380),Spacer(1,5),
        p('All four full cycles passed scale-out, recovery within the original 600s window, and repeated scale-out. Protocol: 120s baseline, 180s/9,450-offer spike, 600s zero arrivals, identical repeat spike, 30s observation. Worker-only tests held the API at four Ready replicas. Detailed per-cycle traffic/backlog plots and timing values are in hpa-summary.csv and hpa-*.png/svg.',SMALL)]
    pages.append(page_pdf(items,baseline_count+3,landscape(A4)))
    items=[p('Capacity, HTTP failures and delivery validity - TC-23',HEADING),
        figure('traffic-offered-achieved.png',758,390),Spacer(1,5),
        p('Circles: fresh trials; crosses: original baseline; triangles: unreconciled HTTP-acknowledgement lower bounds. Hollow markers identify invalid delivery. P95 alone is insufficient: one 250/s four-replica trial had P95 536ms but 158 HTTP timeouts and therefore missed the SLO. No 300/s attempt established a complete passing result.',SMALL)]
    pages.append(page_pdf(items,baseline_count+4,landscape(A4)))
    return pages


def main():
    audit=read(EVIDENCE/'raw-audit.json');completion=read(EVIDENCE/'completion.json')
    assert audit['status']=='PASS' and not audit['failed'] and completion['pending_units']==0
    capacity=read(REPORT/'capacity-summary.json');bursts=read(REPORT/'burst-summary.json')
    scheduler=read(REPORT/'scheduler-summary.json')
    baseline=REFRESH/'before/output/pdf'/(STEM+'.pdf')
    if not baseline.exists():raise RuntimeError('Preserve current submission documents in document-refresh/before first')
    block(OUT/'GROUP02_INSTRUCTIONS.md','supplements',
          (ROOT/'docs/FOLLOWUP_TESTING_APPENDIX.md').read_text(encoding='utf-8'))
    original=PdfReader(baseline);count=len(original.pages)
    assert count==22,'Expected the preserved 22-page baseline'
    writer=PdfWriter();writer.append(original,import_outline=True)
    overlay=BytesIO();c=canvas.Canvas(overlay,pagesize=A4);c.setFont('Helvetica-Bold',7.2);c.setFillColor(TEAL)
    c.drawString(42,36,f'19 November 2026 follow-up: Appendix A, pages {count+1}-{count+4}. Original 25-case baseline retained.')
    c.save();overlay.seek(0);writer.pages[0].merge_page(PdfReader(overlay).pages[0])
    for i,page in enumerate(report_supplement(capacity,bursts,scheduler,count)):
        writer.append(page,import_outline=False)
        writer.add_outline_item(['Latest follow-up: results','Paired scheduler comparisons','Fresh HPA cycles','Capacity and delivery validity'][i],count+i)
    writer.add_metadata({'/Title':'Group 02 - Verified baseline and 19 November follow-up results','/Author':'CSC3104 Group 02'})
    target=OUT/(STEM+'.pdf')
    with target.open('wb') as stream:writer.write(stream)
    supplement=(ROOT/'docs/FOLLOWUP_EVALUATION_RESULTS.md').read_text(encoding='utf-8')
    supplement=re.sub(r'<!-- followup-20261119:document-sync:start -->.*?<!-- followup-20261119:document-sync:end -->','',supplement,flags=re.S)
    supplement=supplement.partition('\n')[2].replace('../output/validation/','../validation/')
    for title,name in (('Paired scheduler comparison','scheduler-paired-comparison'),
                       ('Fresh HPA cycles','hpa-fresh-overview'),('Traffic and delivery validity','traffic-offered-achieved')):
        supplement+=f'\n\n### {title}\n\n![{title}](../validation/followup-20261119/report/{name}.png)\n'
    block(OUT/(STEM+'.md'),'latest-results','## Appendix A - Latest measured follow-up\n\n19 November 2026. Original baseline above is retained; the PDF supplement begins on page 23.\n\n'+supplement)
    block(OUT/(STEM+'.md'),'notice','**19 November 2026 follow-up:** this report now includes the latest measured scheduler, HPA, capacity and burst results in Appendix A. The earlier 25-case baseline below remains dated and unchanged.',prefix=True)
    from build_instructions import build
    build()
    guide=OUT/'GROUP02_INSTRUCTIONS.pdf';reader=PdfReader(guide);guide_writer=PdfWriter()
    guide_writer.clone_document_from_reader(reader)
    overlay=BytesIO();c=canvas.Canvas(overlay,pagesize=A4);c.setFont('Helvetica-Bold',7.2);c.setFillColor(TEAL)
    c.drawString(42,37,'19 November 2026 follow-up: see Appendix A. Original 25-case baseline retained.')
    c.save();overlay.seek(0);guide_writer.pages[0].merge_page(PdfReader(overlay).pages[0])
    with guide.open('wb') as stream:guide_writer.write(stream)
    print('Updated report:',len(PdfReader(target).pages),'pages')
    print('Updated instructions:',len(PdfReader(OUT/'GROUP02_INSTRUCTIONS.pdf').pages),'pages')


if __name__=='__main__':main()
