/* Real Chromium UI checks for the documented examiner journeys.
 * Run only with examiner_verify.py against its fresh isolated lab.
 * Browser profiles stay private under .local; JSON exports exclude cookies.
 */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const assert = require('assert/strict');
const { chromium } = require(process.env.EXAM_PLAYWRIGHT);
const [base, mode, output, profile, inputFile] = process.argv.slice(2);
const root = path.resolve(__dirname, '..');
const input = inputFile ? JSON.parse(fs.readFileSync(inputFile, 'utf8')) : {};
const token = JSON.parse(fs.readFileSync(path.join(root,'.local/k8s/secrets-csc3104-lab.json'),'utf8')).PAYMENT_API_TOKEN;
const password = crypto.createHmac('sha256',token).update('csc3104:admin-password').digest('hex');
const executablePath = [process.env.EXAM_BROWSER,'C:/Program Files/Google/Chrome/Application/chrome.exe','C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find(p=>p&&fs.existsSync(p));
if (!executablePath) throw new Error('An installed Chrome or Edge is required; no browser download was attempted');
fs.mkdirSync(output,{recursive:true});
let context, page;
const errors=[];
const result={mode,started_at:new Date().toISOString(),engine:'Chromium',executable:executablePath,checks:{}};
const check=(name,value)=>{result.checks[name]=Boolean(value);assert.ok(value,name);};
const save=(name,value)=>fs.writeFileSync(path.join(output,name),JSON.stringify(value,null,2));
async function launch(){
  context=await chromium.launchPersistentContext(profile,{executablePath,headless:true,viewport:{width:1440,height:1000}});
  result.browser_version=context.browser()?.version();
  context.setDefaultTimeout(20000);
  context.on('page',p=>p.on('pageerror',e=>errors.push(String(e))));
  page=context.pages()[0]||await context.newPage();
  page.on('pageerror',e=>errors.push(String(e)));
  await page.goto(base);await page.waitForFunction(()=>typeof getCurrentRequest==='function' && typeof window.getCurrentCheckout==='function');
  await page.locator('#register-form').waitFor({state:'attached'});
}
async function shot(name,p=page){await p.screenshot({path:path.join(output,name+'.png'),fullPage:true});}
async function state(p=page){return p.evaluate(()=>({user:getCurrentUser(),request:getCurrentRequest(),checkout:window.getCurrentCheckout()}));}
async function waitStatus(status,p=page,timeout=120000){
  await p.waitForFunction(s=>window.getCurrentCheckout()?.booking_status===s,status,{timeout});return state(p);
}
async function customer(name,section,size){
  await page.locator('[data-tab="join"]').click();
  await page.locator('#new-demo-user').click();
  await page.locator('#register-form input[name="name"]').fill(name);
  await page.locator('#register-form button[type="submit"]').click();
  await page.locator('#join-form select[name="section"]').selectOption(section);
  await page.locator('#join-form select[name="party_size"]').selectOption(String(size));
  await page.locator('#join-form button[type="submit"]').click();
  await page.waitForFunction(()=>Boolean(getCurrentRequest()?.request_id));
  return state();
}
async function admin(p){
  await p.goto(base);await p.locator('#admin-access').click();
  await p.locator('#admin-password').fill(password);await p.locator('#admin-login-submit').click();
  await p.waitForFunction(()=>document.querySelector('#admin-access').textContent==='Sign out of admin');
  await p.locator('[data-tab="admin"]').click();
}
async function startSale(){
  const b=await chromium.launch({executablePath,headless:true});const c=await b.newContext();const p=await c.newPage();
  try {await admin(p);await p.locator('#start-sale').click();await p.waitForFunction(()=>document.querySelector('#sale-status').textContent.toLowerCase().includes('started'));}
  finally {await b.close();}
}
async function selectExisting(user,p=page){
  await p.locator('[data-tab="join"]').click();await p.locator('#refresh-demo-users').click();
  await p.locator('#demo-user-select').selectOption(user.user_id);await p.locator('#view-demo-user').click();
  await p.waitForFunction(id=>getCurrentRequest()?.user_id===id,user.user_id);
}
async function pay(){await page.locator('#ticket-pay').click();return waitStatus('confirmed');}
function same(original,restored){
  return original.request.request_id===restored.request.request_id && original.checkout.hold_id===restored.checkout.hold_id &&
    original.request.queue_number===restored.request.queue_number && original.checkout.original_hold_expiry===restored.checkout.original_hold_expiry &&
    JSON.stringify(original.checkout.seats.map(s=>s.seat_id))===JSON.stringify(restored.checkout.seats.map(s=>s.seat_id));
}
async function perform(){
  await launch();
  if(mode==='journeys'){
    const cases={};
    await customer('Alice Final','A',2);await startSale();const a=await waitStatus('active');await shot('TC01-reserved');
    const ac=await pay();await page.reload();await waitStatus('confirmed');const ar=await state();
    check('TC01_same_ids_seats_deadline_after_payment_reload',same(a,ar));check('TC01_two_adjacent_confirmed',ar.checkout.seats.length===2 && ar.checkout.seats.every(s=>s.state==='CONFIRMED') && ar.checkout.seats[0].row===ar.checkout.seats[1].row && Math.abs(ar.checkout.seats[0].position_in_row-ar.checkout.seats[1].position_in_row)===1);
    await shot('TC01-confirmed-reloaded');cases['TC-01']={before:a,confirmed:ac,after_reload:ar};
    await customer('Bob Final','B',2);const b=await waitStatus('active');await page.locator('#ticket-decline').click();
    await page.waitForFunction(()=>window.getCurrentCheckout()?.payment_attempts?.some(p=>p.attempt_status==='declined'));
    const bd=await state();await shot('TC02-declined');check('TC02_decline_keeps_original_active_hold',same(b,bd)&&bd.checkout.booking_status==='active'&&bd.checkout.seats.every(s=>s.state==='HELD'));
    const bc=await pay();check('TC02_retry_same_hold_original_deadline',same(b,bc));await shot('TC02-confirmed');cases['TC-02']={before:b,declined:bd,confirmed:bc};
    await customer('Carol Final','C',3);const c=await waitStatus('active');page.once('dialog',d=>d.accept());await page.locator('#ticket-cancel').click();
    const cc=await waitStatus('cancelled');await page.reload();await waitStatus('cancelled');const cr=await state();
    check('TC03_terminal_after_reload',same(c,cr)&&cr.checkout.can_pay===false&&cr.checkout.seats.every(s=>s.state==='AVAILABLE'));
    await shot('TC03-cancelled-reloaded');cases['TC-03']={before:c,cancelled:cc,after_reload:cr};
    await customer('Dan Final','D',1);const d=await waitStatus('active');await shot('TC04-reserved');
    save('journeys-progress.json',cases);save('expiry-before.json',d);
    console.log('Waiting for the original 300-second hold expiry; no deadline changes');
    await waitStatus('expired',page,340000);await page.reload();const de=await waitStatus('expired');await shot('TC04-expired-reloaded');
    const access=await (await context.request.get(base+'/api/session')).json();
    const late=await context.request.post(base+'/api/payment/payments',{headers:{'X-CSRF-Token':access.csrf},data:{request_id:d.request.request_id,hold_id:d.checkout.hold_id,outcome:'success',attempt_key:'late-final-'+d.request.request_id}});
    check('TC04_actual_late_payment_409_same_expired_hold',late.status()===409&&same(d,de)&&de.checkout.seats.every(s=>s.state==='AVAILABLE'));
    cases['TC-04']={before:d,expired:de,late_payment_status:late.status(),late_payment_body:await late.json()};result.cases=cases;
  }else if(mode==='capacity'){
    const users=[];for(let i=1;i<=3;i++)users.push((await customer('C'+i+' Final','C',4)).user);
    await startSale();const outcomes=[];
    for(const u of users){await selectExisting(u);await page.waitForFunction(()=>['RESERVED','UNAVAILABLE'].includes(getCurrentRequest()?.status));const s=await state();outcomes.push(s);await shot('TC05-'+u.name.replace(/ /g,'-'));}
    const reserved=outcomes.filter(s=>s.request.status==='RESERVED');check('TC05_exact_two_whole_parties_one_unavailable',reserved.length===2&&outcomes.filter(s=>s.request.status==='UNAVAILABLE').length===1);
    await selectExisting(reserved[0].user);const before=await waitStatus('active');
    const p2=await context.newPage();await p2.goto(base);await selectExisting(before.user,p2);const second=await waitStatus('active',p2);
    await page.reload();await p2.reload();const a=await waitStatus('active');const b=await waitStatus('active',p2);
    check('TC05_both_tabs_match_before_after_refresh',same(before,second)&&same(before,a)&&same(before,b));
    await shot('TC05-tab-one-reloaded');await shot('TC05-tab-two-reloaded',p2);result.outcomes=outcomes;result.tabs={before,second,after:[a,b]};
  }else if(mode==='service-flow'){
    await customer('Alice Service Final','A',2);await startSale();await waitStatus('active');const original=await pay();
    const b=await chromium.launch({executablePath,headless:true});const c=await b.newContext();const p=await c.newPage();
    try{await admin(p);await p.locator('#simulate-form input[name="count"]').fill('4');await p.locator('#simulate-form select[name="section"]').selectOption('B');await p.locator('#simulate-form select[name="party_size"]').selectOption('1');await p.locator('#simulate-form button[type="submit"]').click();await p.waitForFunction(()=>document.querySelector('#queue-table').innerText.includes('sim-'));await shot('TC07-overview-after-simulation',p);await p.locator('[data-tab="batches"]').click();await shot('TC07-batches',p);}
    finally{await b.close();}result.original=original;await shot('TC07-original-confirmed');
  }else if(mode==='recovery'){
    await customer('Return Final','D',1);await startSale();await waitStatus('active');
    // Produce a real payment ID for the cross-profile read check; a decline
    // retains the same original hold and expiry used by the recovery journey.
    await page.locator('#ticket-decline').click();
    await page.waitForFunction(()=>window.getCurrentCheckout()?.payment_attempts?.some(p=>p.attempt_status==='declined'));
    const before=await state();await shot('TC25-before');
    await context.setOffline(true);await page.reload().catch(()=>{});await new Promise(r=>setTimeout(r,3000));await context.setOffline(false);await page.goto(base);const refreshed=await waitStatus('active');
    check('TC25_disconnect_refresh_preserves_identity',same(before,refreshed));
    await context.close();context=null;await launch();await selectExisting(before.user);const reopened=await waitStatus('active');
    check('TC25_browser_process_closed_reopened_same_booking',same(before,reopened));await shot('TC25-reopened');
    const b=await chromium.launch({executablePath,headless:true});const other=await b.newContext();const p=await other.newPage();
    const denials=[];
    try{
      await p.goto(base);const access=await (await other.request.get(base+'/api/session')).json();
      const paymentId=before.checkout.payment_attempts[0].payment_id;
      const paths=[['waiting-room/requests/'+before.request.request_id,null],['payment/payments/'+paymentId,null],['payment/payments/'+paymentId+'/details',null],['payment/payments',{request_id:before.request.request_id,hold_id:before.checkout.hold_id,outcome:'success',attempt_key:'forged-final'}],['payment/checkouts/cancel',{request_id:before.request.request_id,hold_id:before.checkout.hold_id,action_key:'forged-final'}],['waiting-room/sale/start',{}],['seats/seats/confirm',{request_id:before.request.request_id,hold_id:before.checkout.hold_id}]];
      for(const [route,body] of paths){const response=body===null?await other.request.get(base+'/api/'+route):await other.request.post(base+'/api/'+route,{headers:{'X-CSRF-Token':access.csrf},data:body});denials.push({path:route,status:response.status(),body:await response.json()});check('TC25_denied_'+route,response.status()===403);}
      await admin(p);check('TC25_admin_controls_visible_after_sign_in',await p.locator('#start-sale').isVisible());await shot('TC25-admin-signed-in',p);
      await p.locator('#admin-access').click();await p.waitForFunction(()=>document.querySelector('.admin-group').hidden);check('TC25_admin_controls_removed_after_sign_out',await p.locator('#start-sale').isHidden());await shot('TC25-admin-signed-out',p);
      const deniedAgain=await other.request.get(base+'/api/waiting-room/requests/'+before.request.request_id);check('TC25_sign_out_revokes_privileged_read',deniedAgain.status()===403);
    }finally{await b.close();}
    await page.reload();const after=await waitStatus('active');check('TC25_denials_cause_no_booking_mutation',same(before,after)&&JSON.stringify(after.checkout.payment_attempts)===JSON.stringify(before.checkout.payment_attempts)&&after.checkout.cancellation===null);
    result.before=before;result.reopened=reopened;result.after=after;result.denials=denials;
    const expiry=Date.parse(before.checkout.original_hold_expiry)-Date.now();console.log('Checking return after original expiry; waiting '+Math.max(0,Math.ceil(expiry/1000))+' seconds');
    await context.close();context=null;await new Promise(r=>setTimeout(r,Math.max(0,expiry)+3000));await launch();await selectExisting(before.user);const expired=await waitStatus('expired',page,30000);check('TC25_late_return_honest_expiry_same_identity',same(before,expired)&&expired.checkout.can_pay===false);result.expired=expired;await shot('TC25-return-expired');
    // The owner may record a cancellation against an already-expired hold;
    // this produces a genuine action ID without releasing/rebooking any seat.
    const ownerAccess=await (await context.request.get(base+'/api/session')).json();
    const cancelReply=await context.request.post(base+'/api/payment/checkouts/cancel',{headers:{'X-CSRF-Token':ownerAccess.csrf},data:{request_id:before.request.request_id,hold_id:before.checkout.hold_id,action_key:'owner-expired-access-check'}});
    check('TC25_owner_expired_action_records_same_terminal_state',cancelReply.status()===200);
    const action=await cancelReply.json();check('TC25_real_cancellation_action_exists',Boolean(action.action_id)&&action.status==='expired');result.owner_expired_action=action;
    const probeBrowser=await chromium.launch({executablePath,headless:true});
    try{const probe=await probeBrowser.newContext();const response=await probe.request.get(base+'/api/payment/cancellations/'+action.action_id);check('TC25_copied_real_cancellation_id_denied',response.status()===403);result.denials.push({path:'payment/cancellations/'+action.action_id,status:response.status(),body:await response.json()});}
    finally{await probeBrowser.close();}
    await page.reload();const stillExpired=await waitStatus('expired');check('TC25_expired_identity_seats_deadline_remain_unchanged',same(expired,stillExpired));result.after_real_action_probe=stillExpired;
  }else if(mode==='register-pre'||mode==='reserve'||mode==='book'){
    await customer(input.name||'Fault Final',input.section||'A',input.size||2);
    if(mode!=='register-pre'){await startSale();await waitStatus('active');if(mode==='book')await pay();}
    result.booking=await state();await shot(mode);
  }else if(mode==='inspect'||mode==='pay-pending'||mode==='pay-existing'){
    await selectExisting(input.user);await page.waitForFunction(()=>Boolean(getCurrentRequest()?.allocation));
    if(mode==='pay-pending'){await page.locator('#ticket-pay').click();await page.waitForFunction(()=>window.getCurrentCheckout()?.payment_attempts?.some(p=>p.attempt_status==='pending'));}
    else if(mode==='pay-existing'){await waitStatus('active');await pay();}
    else if(input.status)await waitStatus(input.status);
    result.booking=await state();if(input.original)check('same_original_booking',same(input.original,result.booking));await shot(mode);
  }else throw new Error('Unknown mode '+mode);
  check('no_browser_javascript_errors',errors.length===0);result.javascript_errors=errors;result.status='PASS';
}
(async()=>{try{await perform();}catch(e){result.status='FAIL';result.error=String(e);result.stack=e.stack;await shot('failure').catch(()=>{});process.exitCode=1;}finally{if(context)await context.close();result.finished_at=new Date().toISOString();save('browser-result.json',result);console.log(mode+': '+result.status);}})();
