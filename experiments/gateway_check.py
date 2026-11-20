"""Exercise real browser cookies through the lab's public HTTP gateway."""
from http.cookiejar import CookieJar
from urllib.request import build_opener,HTTPCookieProcessor,Request
from urllib.error import HTTPError
import hashlib
import hmac
import json
from runtime import LAB,guard_lab,local,write_json


def gateway_check(base,directory):
    guard_lab(base)
    def browser():
        opener=build_opener(HTTPCookieProcessor(CookieJar()))
        def call(path,body=None,expected=200):
            headers={'Content-Type':'application/json'}
            if body is not None and 'csrf' in state:headers['X-CSRF-Token']=state['csrf']
            req=Request(base+'/api/'+path,data=None if body is None else json.dumps(body).encode(),headers=headers)
            try:
                with opener.open(req,timeout=15) as response:status,data=response.status,json.load(response)
            except HTTPError as error:status,data=error.code,json.load(error)
            if status!=expected:raise AssertionError((path,status,expected,data))
            return data
        state={};state.update(call('session'))
        if not state.get('enabled'):raise RuntimeError('Gateway ownership is not enabled')
        return call
    first,second=browser(),browser()
    a=first('session/identities',dict(name='Gateway Alice',key=directory.name+'-alice'))
    b=second('session/identities',dict(name='Gateway Bob',key=directory.name+'-bob'))
    party=first('waiting-room/submit',dict(user_id=a['user_id'],section='A',party_size=1),201)
    rid=party['request_id']
    assert first('waiting-room/requests/'+rid)['user_id']==a['user_id']
    checks=[]
    for path,body in [('waiting-room/requests/'+rid,None),('waiting-room/submit',dict(user_id=a['user_id'],section='A',party_size=1)),
        ('payment/payments',dict(request_id=rid,hold_id='copied',attempt_key='forged',outcome='success')),
        ('payment/checkouts/cancel',dict(request_id=rid,hold_id='copied',action_key='forged')),
        ('waiting-room/sale/start',{}),('seats/seats/confirm',dict(request_id=rid,hold_id='copied'))]:
        second(path,body,403);checks.append(dict(path=path,status=403))
    assert [p['user_id'] for p in first('waiting-room/queue')['requests']]==[a['user_id']]
    assert not second('waiting-room/queue')['requests']
    token=json.loads((local.LOCAL/('secrets-'+LAB+'.json')).read_text())['PAYMENT_API_TOKEN']
    password=hmac.new(token.encode(),b'csc3104:admin-password',hashlib.sha256).hexdigest()
    second('session/admin',{'password':'wrong'},403)
    second('session/admin',{'password':password})
    assert second('session')['admin'] is True
    assert any(p['request_id']==rid for p in second('waiting-room/queue')['requests'])
    second('session/logout',{})
    second('waiting-room/requests/'+rid,None,403)
    result=dict(status='PASS',request_id=rid,denied=checks,
        checks=['owned registration/read','cross-browser denial','queue isolation','admin sign-in/sign-out'],
        scope='Real HTTP cookies and gateway authorization; not a live-browser visual check or a penetration test')
    write_json(directory/'summary.json',result);return result
