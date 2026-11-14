"""Render the verified report and merge both supplied reports as history.

Refuses publication unless the raw all25 audit has passed. No tests are run.
Original PDFs/Markdown are preserved before updating the submission report.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import shutil
from html import escape
from io import BytesIO

from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, PageBreak, Image

from build_instructions import STYLES, make_table, markup

STYLES['body']=STYLES['body'].clone('body',fontSize=10.2,leading=14.0,spaceAfter=8)

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/pdf'
STEM='GROUP02_Test_Results_and_Distributed_Concepts_Report'

NAMES={1:'Register, allocate, pay and refresh',2:'Decline and retry the same hold',3:'Cancel the whole unpaid party',4:'Original expiry and actual late-payment rejection',5:'Whole-party capacity and same-user tabs',6:'Invalid input and unknown identifiers',7:'Asynchronous handoffs and late arrivals',8:'Concurrent seat ownership',9:'Compose packaging and internal networking',10:'Kubernetes API replacement and Service routing',11:'Durable payment with no consumer',12:'Queued allocation with no consumer',13:'Payment recovery through seat API outage',14:'Single-request baseline',15:'Scheduled registration',16:'One, two and four allocation workers',17:'Store pod replacement with retained PVCs',18:'Demand-Cycle versus FCFS',19:'Thousands of arrivals and mixed parties',20:'Payment, cancellation and expiry races',21:'Lost committed reply and abrupt worker crash',22:'Sustained Redis/PostgreSQL outages',23:'Waiting-room API replicas and tested capacity',24:'Automatic scale out, in and out again',25:'Browser ownership, disconnection and return'}
CONCEPTS={
1:'Cooperating services retain one business identity; authoritative seat ownership survives browser reload.',
2:'Payment attempts and reservations have separate state. Retrying a decline does not extend scarce inventory ownership.',
3:'Whole-party release and terminal cancellation protect unrelated ownership and prevent abandoned seat fragments.',
4:'Time-bounded claims are reclaimed asynchronously; the backend rejects late payment independently of a client countdown.',
5:'All-or-nothing party allocation and server-authoritative records keep capacity safe across multiple client views.',
6:'Stable service contracts reject malformed input before it becomes queue work; HTTP400 and404 have distinct meanings.',
7:'Durable asynchronous stages converge through correlated request, batch and hold IDs and delivered completion receipts.',
8:'Concurrent clients contend for one inventory while seat-store transactions and locks preserve unique ownership.',
9:'Separate containers communicate through internal service names; API and storage ports need not be public.',
10:'A controller replaces application compute and a stable Service routes to the Ready replacement; state lives outside the API pod.',
11:'Durable acceptance is separate from execution. A paused consumer does not lose payment intent or falsely confirm seats.',
12:'A saved allocation job progresses after its worker returns, without another registration or a replacement business identity.',
13:'Partial dependency failure retains pending work with backoff. Recovery preserves the original hold and deadline.',
14:'A direct one-sample HTTP baseline is useful instrumentation, but is not an end-to-end booking latency distribution.',
15:'An open-loop arrival schedule separates admission service time, generator launch lag and acknowledged identity retention.',
16:'Horizontal worker scaling is tested against equivalent physical inventory, workload and policies. Four sections bound useful parallelism.',
17:'StatefulSets reuse persistent volumes across pod replacement. A fresh booking after recovery proves forward progress beyond old-data reads.',
18:'Controlled paired policies expose reservation, wait, utilization and fairness trade-offs rather than assuming one policy is superior.',
19:'Burst admission needs both a valid load generator and efficient bounded state access; seat safety remains independently authoritative.',
20:'Concurrent lifecycle operations must converge to one consistent terminal winner without duplicate payment or conflicting seat ownership.',
21:'At-least-once transport can lose replies after commit. Stable request identities, leases and fencing support one business effect.',
22:'Durable queue and booking records survive temporary storage unavailability; service availability during the outage is a separate property.',
23:'A valid replica comparison needs complete equal offered traffic and proof each requested pod actually served requests.',
24:'Elasticity is observed behavior under real demand: CPU signals and actual Ready counts must demonstrate the complete automatic cycle.',
25:'Signed browser ownership and privileged administrator sessions separate customer recovery from cross-user access; these are not verified accounts.'}


def read(p):return json.loads(p.read_text(encoding='utf-8'))


def facts(n, selected):
    folder=ROOT/selected['evidence']
    if n in (1,2,3,4):
        d=read(folder/'browser/browser-result.json')['cases'][f'TC-{n:02}']
        c=d['after_reload']['checkout'] if n in (1,3) else d['confirmed']['checkout'] if n==2 else d['expired']['checkout']
        seats=', '.join(s['seat_id'] for s in c['seats'])
        statements={1:f'Two adjacent A seats ({seats}) confirmed for the original request/hold and retained after actual browser reload.',2:f'A real decline kept the original active hold; a successful retry confirmed {seats} without extending the original deadline.',3:f'The three-seat C party became CANCELLED. All original seats ({seats}) became AVAILABLE; reload remained terminal and payment unavailable.',4:f'The unchanged five-minute D hold became EXPIRED and its seat ({seats}) became AVAILABLE. An actual payment POST against that same expired hold returned HTTP {d.get("late_payment_status")}.'}
        return statements[n],f'Request {c["request_id"]}; hold {c["hold_id"]}; original deadline {c["original_hold_expiry"]}.'
    if n==5:return 'Exactly two C/4 parties reserved eight of ten seats; the third was UNAVAILABLE. Both tabs were actually refreshed and retained the same request, hold, seats, queue position and original deadline. SQL invariants passed.','Raw browser states and both after-refresh screenshots are retained.'
    if n==6:return 'Six invalid registrations returned HTTP 400; nonexistent request and section reads returned HTTP 404. The complete before/after queue was identical.','Eight real HTTP assertions; no valid booking was created by this case.'
    if n==7:return 'The original A/2 customer confirmed. Four B/1 parties added through the real administrator Simulate users form automatically reserved as latecomers. Five distinct requests correlated; dispatcher work completed and allocation completion receipts delivered.','The optional payment callback is outside the delivered allocator-completion claim.'
    if n==8:
        d=read(folder/'summary.json');return f'All20 original concurrent clients completed: ten RESERVED, ten UNAVAILABLE, no UNKNOWN. Peak overlapping HTTP requests={d["peak_overlapping_client_requests"]}; ten unique seats and zero SQL violations.','Direct seat-store contention bypasses queue scheduling and payment.'
    if n==9:return 'The submitted launcher and Compose file started 13 runtime containers; all three initialization containers exited with code 0. Only frontend loopback was published; proxied PostgreSQL seat-store health succeeded. The isolated test project was then stopped, with volumes retained.','Project-name/port isolation preserved pre-existing deployments; this is local container evidence.'
    if n==10:return 'A confirmed booking survived actual allocation API pod deletion. The replacement had a new UID and a Ready Service endpoint; all three API probes were configured, original PVC identities remained, and browser reload retained the same confirmed booking.','This checks pod replacement, not injected probe failure, continuous availability or node failover.'
    if n==11:return 'With zero payment-worker pods, a real browser submitted one payment. It remained pending, API health stayed available and no seat falsely confirmed. Restoration completed that same payment/hold exactly once, with original seats/deadline and passing invariants.','A controlled consumer pause is distinct from an abrupt commit-boundary crash (TC-21).'
    if n==12:return 'With zero allocator pods, the original B/2 request remained as a zero-attempt queued job with no hold. The restored worker reserved the same request; browser payment confirmed it once and SQL invariants passed.','An empty paused inventory is not treated as a booking safety PASS; final nonempty ownership is checked.'
    if n==13:return 'Seat API had zero pods while payment-worker was Ready. Real dependency failures retained one pending payment and one unconfirmed hold; checkout returned HTTP 503. After restoration the original payment confirmed the same hold/seats before the unchanged expiry.','The initial diagnostic-query error is retained separately; the completed corrected rerun supplies this result.'
    if n==17:return 'Both PostgreSQL/Redis pod UIDs changed while PVC UIDs and volume identities stayed the same. Complete captured holds, seats, payments, allocation jobs and queue matched strictly before/after; the original browser booking survived and a new booking confirmed.','The comparison does not silently remove metadata fields. Retained local storage is not storage HA or a backup.'
    if n==25:
        d=read(folder/'browser/browser-result.json');return f'Offline refresh, complete browser-process close/reopen and saved-customer selection recovered the same original booking. All {len(d["denials"])} copied-identity/mutation attempts in a second profile returned HTTP 403. Admin sign-in/out toggled privilege; denials left the booking unchanged. A second cold return after real expiry showed EXPIRED.','No second registration occurred. Browser cookies last seven days, but real elapsed seven-day survival was not tested; cookie deletion and verified-account recovery are not promised.'
    if n==14:return 'Three fresh trials each made one C/1 direct HTTP request: one reservation each, no unknown outcome and zero invariant violations. Each trial has one timing sample, so mean=P95 within a trial.','Read actual per-run timings in tc-fix-regression-v9-TC14-r1/r2/r3/metrics.json.'
    if n==15:return 'Three fresh pre-sale trials each delivered 50/50 offers at 5/s for 10 seconds, with the original one-second maximum launch lag, no rejected/unknown/dropped offers and no missing acknowledgements.','This measures admission and response drain, not paid bookings/s.'
    if n==16:return 'The F1 trace (40 parties, seed 42, batch 10, TTL 120 seconds) ran with 1/2/4 workers, three repeats each, both policies and matching fresh inventory. All 18 policy replays passed their terminal-outcome and safety criteria.','Compare the same policy across worker counts; more replicas do not guarantee improvement.'
    if n==18:return 'Ten independent F1 seeds 42-51 ran with both policies at one worker, producing 20 passing policy replays and 40 interpretable paired section observations. Identical input fingerprints and fresh physical inventory were checked.','These descriptive results do not certify optional F2-F7 explorations, statistical significance or fairness superiority.'
    if n==19:return 'Three complete original 2,100-offer surges passed. Admission completed in 172.24/168.76/158.32 seconds (all below 600 seconds), with maximum launch lag below 0.029 seconds. The mixed test used 40 parties, sizes 1-4 and 32 clients, safely allocating ten C seats.','All final offers delivered; no HTTP failure, generator drop, missing/duplicate ID, upstream retry or SQL violation.'
    if n==20:return 'Three active and three near-expiry payment/cancellation races passed. The original 20-second near-expiry holds and simultaneous release barrier were retained; each run ended with a consistent confirmed/cancelled/expired winner and zero SQL violations.','A particular winner is not required; asynchronous execution order may differ.'
    if n==21:return 'The proxy committed a real seat hold before dropping its reply; the crash variant additionally SIGKILLed the worker at that checkpoint and observed restart. Both recovered the same request, original hold and deadline, with one hold history and zero SQL violations.','Specific idempotent effects do not imply exactly-once network transport.'
    if n==22:return 'Separate 60-second Redis, PostgreSQL and combined outages preserved a confirmed booking and acknowledged queued work. Restored dependencies allowed the original queued request to allocate safely; all three variants passed.','No claim of uninterrupted availability while stores were down.'
    if n==23:return 'Nine fixed trials each accepted 1,500/1,500 offers at 50/s for 30 seconds. All requested 1/2/4 replicas actually served. Mean trial P95 by replicas was 19.871/16.488/22.142 ms. All 18 capacity points through 200/s passed declared thresholds.','Approximately 50 accepted/s at a fixed offered 50/s is not a speedup. 200/s is the highest passing tested rate, not the true maximum.'
    if n==24:return 'Separate API (19,140 offers) and worker (19,020) cycles both showed actual Ready 1 -> 4 -> 1 -> 4. CPU exceeded the 50% target under load and fell below it during recovery. Worker backlog drained; the first one-worker witness was 589.66 seconds after actual spike offer-end, within 600 seconds.','No manual target scaling after HPA attachment; cleanup deletion is not scale-in. Both original 9,450-offer spikes were retained.'
    raise ValueError(n)


def header(canvas,doc):
    w,h=A4;canvas.setStrokeColor(colors.HexColor('#1B2A41'));canvas.line(42,h-29,w-42,h-29)
    canvas.setFillColor(colors.HexColor('#566477'));canvas.setFont('Helvetica',7.3)
    canvas.drawString(42,h-42,'CSC3104 / GROUP 02 / VERIFIED TEST RESULTS / 14 NOV 2026')
    canvas.drawString(42,22,'Local acceptance evidence; original unsuccessful attempts preserved.')
    canvas.drawRightString(w-42,22,str(doc.page))


class Report(BaseDocTemplate):
    def afterFlowable(self,item):
        if isinstance(item,Paragraph) and item.style.name in ('h1','h2','h3'):
            title=item.getPlainText();self.canv.bookmarkPage(title);self.canv.addOutlineEntry(title,title,0,False)


def render(pdf,blocks):
    doc=Report(str(pdf) if isinstance(pdf,Path) else pdf,pagesize=A4,leftMargin=42,rightMargin=42,topMargin=60,bottomMargin=48,title='Group 02 - Verified 25-case test results',author='CSC3104 Group 02')
    doc.addPageTemplates(PageTemplate(id='results',frames=[Frame(42,48,A4[0]-84,A4[1]-108,leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)],onPage=header))
    doc.build(blocks)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--audit',type=Path,required=True);args=parser.parse_args();args.audit=args.audit.resolve()
    audit=read(args.audit);assert audit['status']=='PASS' and len(audit['cases'])==25 and not audit['failed'],'Refuse to publish all25 PASS without verified evidence'
    assert all(r['status']=='PASS' for r in audit['cases'].values())
    evidence=args.audit.parent;originals=evidence/'original-reports';originals.mkdir(exist_ok=True)
    sources=[(OUT/(STEM+'.pdf'),originals/(STEM+'.pdf')),(Path('C:/Users/linco/Downloads/GROUP02_TWY_Test_Results.pdf'),originals/'GROUP02_TWY_Test_Results.pdf')]
    for source,target in sources:
        if not target.exists():shutil.copy2(source,target)
    if not (originals/(STEM+'.md')).exists():shutil.copy2(OUT/(STEM+'.md'),originals/(STEM+'.md'))
    blocks=[];md=[]
    def text(value,style='body'):
        # Keep numeric measurements intact while making narrative spacing clear.
        for before,after in [('Group02','Group 02'),('All25','All 25'),('All20','All 20'),('All18','All 18'),('all18','all 18'),('all25 PASS','all 25 PASS'),('Verified25','Verified 25'),('original2,100','original 2,100'),('original9,450','original 9,450'),('independent F1 seeds42','independent F1 seeds 42'),('Original13 November','Original 13 November'),('Original14-case','Original 14-case'),('Updated14','Updated 14'),('cohorts:14','cohorts: 14'),('minute target50','minute target 50')]:
            value=value.replace(before,after)
        value=re.sub(r'\b(\d+)(?=(?:independent|passing|interpretable|logical|original|capacity|requested|copied|second|runtime|fresh|November)\b)',r'\1 ',value)
        value=re.sub(r'\b(matched|delivered|producing|and|used|at|within|upstream|approximately|baseline|spike|recovery|repeat|observation|peaked|request|original)(?=\d)',r'\1 ',value)
        blocks.append(Paragraph(markup(value),STYLES[style]));md.append(value)
    def heading(value):text(value,'h2')
    def page():blocks.append(PageBreak());md.append('\n---\n')
    def table(rows):
        lines=['| '+' | '.join(map(str,row))+' |' for row in rows]
        blocks.extend([make_table(lines),Spacer(1,10)]);md.extend(lines)
    text('Fair Seat Allocation','h1');heading('Verified Test Results and Distributed Systems Concepts')
    text('CSC3104 Cloud and Distributed Computing | Group 02 | Updated 14 November 2026')
    text('All25 distinct documented test cases passed their recorded local acceptance conditions. This result combines fifteen newly completed final-version functional/browser/deployment checks with ten full original-scope final v9 studies, whose raw evidence was independently re-audited. It is not a promise that every case will pass on another machine or a production reliability estimate.')
    text('The application/configuration source matched96 files in the final v9 snapshot. No application code was changed for the new functional verification. New harnesses reuse existing lab, workload and invariant tools. Original rates, counts, hold deadlines and safety checks were retained.')
    text('The consolidated results below supersede the older coverage/status statements in the two original reports. Both originals are preserved as clearly labelled historical appendices in the combined PDF; their failed/inconclusive attempts are not relabelled. Historical pages retain their original numbering; use PDF bookmarks to navigate between sections.')
    text('Verification ledger: '+str(args.audit.relative_to(ROOT)).replace('\\','/')+'. All case IDs, raw folder references, retries and independent checks are retained there.')
    previous=read(evidence/'final-acceptance-audit.json')
    text(f'Independent verification: {len(audit["checks"])} new evidence/coverage/continuity checks and {len(previous["checks"])} original-workload raw checks passed, with zero failed checks. These counts are distinct from the 25 case IDs and are not a statistical reliability estimate.')
    text('Validation completed: '+audit['created_at']+'. Existing final cohorts:14 November2026. New observations and exact source/image/configuration details are in each run folder.')
    text('Scope: local single-node Kind and isolated Compose; mock payments; browser sessions. No verified accounts, node failover, storage HA, consensus, exactly-once transport or public production security is claimed.')
    page();heading('All25-case result matrix')
    text('TC-01 to TC-13, TC-17 and TC-25: new final-version checks. TC-14/15/16/18/19/20/21/22/23/24: full-scope final v9 runs, independently re-audited with unchanged application sources. Each case below links its actual cohort.')
    table([['Case / observed result','Scenario']]+[[f'TC-{n:02} - PASS',NAMES[n]] for n in range(1,26)])
    for n in range(1,26):
        if n%2==1:page()
        case=f'TC-{n:02}';selected=audit['cases'][case];observed,limit=facts(n,selected)
        text(case+' | '+NAMES[n]+' | PASS','h3')
        text('**Observed result.** '+observed)
        text('**Cloud/distributed systems significance.** '+CONCEPTS[n])
        text('**Interpretation and detail.** '+limit)
        text('**Evidence.** '+selected['evidence']+'. Case-level raw checks: all25-audit.json; run/cohort: '+selected['run']+'.')
        blocks.append(Spacer(1,12))
    page();heading('Measured scaling results and interpretation')
    text('TC-23 fixed offer=50/s x30s. Each1/2/4 setting repeats three times with fresh equivalent storage and actual serving-pod identities. Rates include response drain. The following values are actual saved v9 measurements.')
    s=read(ROOT/'.local/test-results/tc-fix-23-v9/summary.json')
    rows=[['Repeat / replicas','Accepted','P95ms','Max lag s']]
    for r in s['results']:
        # Raw arrivals provide metrics independent of optional summary aliases.
        d=ROOT/'.local/test-results/tc-fix-23-v9'/f"rate-50-repeat-{r['repeat']}-replicas-{r['replicas']}"
        arrivals=read(d/'arrivals.json');values=sorted(a['response']['elapsed_ms'] for a in arrivals);at=(len(values)-1)*.95;lo=int(at);p95=values[lo]+(values[min(lo+1,len(values)-1)]-values[lo])*(at-lo)
        lag=max(a['launched_seconds']-a['scheduled_seconds'] for a in arrivals)
        rows.append([f"{r['repeat']} / {r['replicas']}",f'{len(arrivals)}/1500',f'{p95:.3f}',f'{lag:.4f}'])
    table(rows)
    text('All final performance cohorts had zero client HTTP failures, generator drops, missing/duplicate IDs, upstream retries or SQL violations. More replicas did not monotonically improve latency. The capacity grid used20/40/60/80/100/s x30s, plus separate200/s points at each replica count; single capacity points do not establish confidence intervals or a true maximum.')
    text('TC-24 phases per target:120s low baseline,180s original9,450-offer spike,600s zero arrivals, identical9,450-offer repeat,30s observation. Actual Ready sequence1->4->1->4 was required. API CPU peaked374% of its50m request and recovered to7%; worker peaked86% of its200m request and recovered to9.1%. Worker limit remained500m. Waiting-room dependency was fixed at four replicas before worker-only measurement.')
    text('Final host/Docker budget:12 logical CPUs, approximately7.69GiB Docker RAM; gateway CPU limit1core, PostgreSQL2cores. The historical TWY report used8CPUs/15.5GiB; timing differences are not a controlled before/after performance comparison.')
    page();heading('Corrections and measurement validity')
    text('The original TWY surge, API-replica and HPA attempts were inconclusive because the offered workload was not fully delivered on schedule and the automatic recovery cycle was not established. Missing offers cannot be counted as successful load. Those original outcomes remain visible in historical appendix A.')
    text('Diagnostics identified client-thread/submission saturation, gateway thread/channel limits and Linux select descriptor limits, Redis global-revision conflicts during simultaneous registration/dispatch, repeated whole-history queue/dispatcher work, polling delays and observed CPU throttling. The fixes reuse the framework: pooled asynchronous arrivals, isolated pooled gateway connections with poll, bounded Redis indexes and fenced scoped updates, append-only transactional dispatcher history, and committed SQL notification hints with durable polling fallback.')
    text('Original arrival rates, counts, identities, inventory, deadlines and SQL assertions were retained. Allocation ranking, global ordering, durable claims, leases and authoritative seat-store transactions remain enforced. The calibrated worker HPA request accounts for its measured idle CPU floor; real sale-open allocation jobs supply load, not synthetic CPU activity. API and worker targets are measured separately.')
    text('Scheduled launch is the headers-send callback after connection acquisition. Client/session preparation is recorded before the offered-arrival epoch; no HTTP connection or registration is warmed up. Connection delay and runtime stalls after the epoch remain subject to the original one-second launch-lag limit. No client submission retries conceal failures; bounded gateway registration recovery is separately counted.')
    text('One intermediate cohort had a genuine upstream502 whose precise original socket cause was not captured by the old handler. It stays inconclusive. Sanitized exception logging and a narrowly idempotent identical-body registration replay were added; a real lost-reply test checks one ID/party/position. Final performance runs used zero upstream retries. No exact cause is invented for that earlier socket event.')
    text('An independent raw-evidence audit rechecks full schedules, HTTP responses, unique acknowledged IDs, stable positions, terminal outcomes, resource/replica evidence, original600-second HPA recovery and SQL invariants. Full diagnostic chronology and source rationale are in output/validation/tc-fixes/ROOT_CAUSES.md and CHANGES.md. Hardware/resource differences prevent a controlled historical latency-speedup claim.')
    for title,files in [
        ('TC-19 original surge delivery and latency',['tc19-surge.png','tc19-traffic-latency.png']),
        ('TC-23 fixed load and sampled resources',['tc23-fixed.png','tc23-resources.png']),
        ('TC-23 tested capacity and shared resources',['tc23-capacity.png','tc23-shared-resources.png']),
        ('TC-24 automatic cycles and worker backlog',['tc24-waiting-room.png','tc24-allocation-worker.png'])]:
        page();heading(title)
        for file in files:
            image=Image(str(ROOT/'output/validation/tc-fixes/report-v9'/file));image._restrictSize(A4[0]-84,300);blocks.extend([image,Spacer(1,12)])
        text('Graphs are generated from saved measured data, not estimated curves. Cached CPU sampling windows differ from client timing. Complete CSV and SVG counterparts are in output/validation/tc-fixes/report-v9/.')
    page();heading('Evidence, earlier attempts and submission limits')
    text('The original missing GROUP02_TWY_Test_Evidence.zip was not recovered. The original TWY PDF was a diagnostic reference. New raw measurements and failures were generated from the repository and retained; the previously sealed replacement TC19/23/24 evidence ZIP remains unchanged.')
    failures=[a for a in audit['attempts'] if a['status']!='PASS']
    if failures:
        text('New preliminary attempts below did not establish acceptance. Their error files remain alongside the completed reruns; only the independently audited complete attempts support the current PASS matrix.')
        table([['Case','Preliminary status','Retained run']]+[[a['case'],a['status'],a['run']] for a in failures])
    text('Evidence trace: all25-audit.json records chosen runs and every preliminary attempt; final-acceptance-audit.json in the same evidence folder rechecks the full v9 workloads. The earlier source reports are historical appendices, including their own scope limits, manual observations and inconclusive scaling runs.')
    text('A Ready pod alone does not prove useful work. A successful HTTP response does not mean a paid booking. UNAVAILABLE can be a valid capacity outcome. Safety, eventual recovery and continuous availability are different properties; these results do not establish uninterrupted availability during faults.')
    text('Retained-state dispatcher upgrades must quiesce both old API and worker before either new process starts. Mixed-version rolling upgrades are unsupported. Fresh isolated lab resets were used for these studies; main storage was not migrated or reset.')
    text('Submit the fixed working source and current image build instructions with raw evidence. Exclude .env.core, kubeconfig, generated Secrets and private browser profiles/cookies. Exported evidence logs must be checked for credentials. Do not infer statistical fairness superiority, arbitrary internet scale or a guarantee of an examiner-machine PASS from this local25/25 result.')
    OUT.mkdir(exist_ok=True,parents=True);pdf=OUT/(STEM+'.pdf');render(pdf,blocks)
    (OUT/(STEM+'.md')).write_text('\n\n'.join(md)+'\n',encoding='utf-8')
    combined=OUT/'GROUP02_Combined_Test_Results.pdf';writer=PdfWriter();writer.append(str(pdf),outline_item='Current verified25-case results')
    for title,description,source in [
        ('Historical appendix A - original TWY report','Original 13 November report, including TC-19/23/24 INCONCLUSIVE attempts. Those attempts remain inconclusive; current corrected results are in the opening report.',sources[1][1]),
        ('Historical appendix B - original functional/concepts report','Original report covering 14 cases and its original manual-evidence limits. Its remaining-coverage statements predate the new complete verification; use the opening report for current status.',sources[0][1])]:
        buffer=BytesIO();render(buffer,[Paragraph(markup(title),STYLES['h2']),Paragraph(markup(description),STYLES['body']),Spacer(1,20),Paragraph('The following original pages are preserved as historical evidence, not the current result ledger.',STYLES['body'])]);buffer.seek(0)
        writer.append(PdfReader(buffer),outline_item=title);writer.append(str(source),import_outline=False)
    writer.add_metadata({'/Title':'Group02 - Combined verified test results and historical source reports','/Author':'CSC3104 Group02'})
    with combined.open('wb') as handle:writer.write(handle)
    for output in (pdf,combined):
        reader=PdfReader(output);assert len(reader.pages)>0 and all((p.extract_text() or '').strip() for p in reader.pages)
        print(output,len(reader.pages),'pages',hashlib.sha256(output.read_bytes()).hexdigest())
    save_manifest={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [pdf,combined,*[s[1] for s in sources]]}
    (evidence/'report-hashes.json').write_text(json.dumps(save_manifest,indent=2),encoding='utf-8')


if __name__=='__main__':main()
