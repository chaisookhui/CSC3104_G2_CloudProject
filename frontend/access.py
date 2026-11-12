"""Browser ownership and operator separation at the public demo gateway.

Guest sessions prove possession of a browser cookie, not a person's identity.
Internal services remain private cluster services; never expose them as ingress.
"""
from datetime import timedelta
import hashlib
import hmac
import os
import re
import secrets

import requests
from flask import jsonify, request, session
from werkzeug.exceptions import ServiceUnavailable


def derived(token, purpose):
    return hmac.new(token.encode(), ('csc3104:'+purpose).encode(), hashlib.sha256).hexdigest()


def install_access(app, services, payment_token):
    enabled=os.getenv('FRONTEND_AUTH','true' if len(payment_token)>=32 else 'false').lower()=='true'
    app.config['ACCESS_ENABLED']=enabled
    if not enabled: return
    if len(payment_token)<32: raise RuntimeError('FRONTEND_AUTH requires a PAYMENT_API_TOKEN of at least 32 characters')
    operator=derived(payment_token,'operator')
    password=os.getenv('FRONTEND_ADMIN_PASSWORD') or derived(payment_token,'admin-password')
    app.secret_key=derived(payment_token,'browser-session')
    namespace=os.getenv('EXPERIMENT_NAMESPACE','native')
    cookie_name='ticketing_'+re.sub(r'[^A-Za-z0-9_-]','_',namespace)[:60]
    app.config.update(SESSION_COOKIE_NAME=cookie_name,SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict',
        SESSION_COOKIE_SECURE=os.getenv('FRONTEND_COOKIE_SECURE','false').lower()=='true',
        PERMANENT_SESSION_LIFETIME=timedelta(days=7), MAX_CONTENT_LENGTH=128*1024)

    def privileged():
        supplied=request.headers.get('Authorization','')
        return hmac.compare_digest(supplied,'Bearer '+operator) or session.get('admin') is True

    def lookup(path):
        try:
            response=requests.get(services['waiting-room'].rstrip('/')+'/'+path,timeout=5)
            if response.status_code>=500: raise ServiceUnavailable()
            if response.status_code!=200: return None
            data=response.json()
            if not isinstance(data,dict):raise ServiceUnavailable()
            return data
        except (requests.RequestException,ValueError):raise ServiceUnavailable() from None

    @app.errorhandler(ServiceUnavailable)
    def ownership_unavailable(error):
        return jsonify(error='Booking ownership could not be verified; retry the same request'),503

    def owned_party(rid):
        party=lookup('requests/'+rid)
        return party if party and party.get('user_id') in session.get('users',{}) else None

    @app.get('/api/session')
    def browser_session():
        session.permanent=True
        if 'principal' not in session: session['principal']=secrets.token_hex(16)
        if 'csrf' not in session: session['csrf']=secrets.token_urlsafe(24)
        return dict(enabled=True,admin=session.get('admin') is True,csrf=session['csrf'],
                    users=[dict(user_id=uid,name=name) for uid,name in session.get('users',{}).items()])

    @app.post('/api/session/identities')
    def identity():
        data=request.get_json(silent=True) or {}
        if not isinstance(data,dict): return dict(error='Expected a JSON object'),400
        name,key=data.get('name'),data.get('key')
        if not isinstance(name,str) or not 1<=len(name.strip())<=40 or not isinstance(key,str) or not 16<=len(key)<=64:
            return dict(error='A name and stable identity creation key are required'),400
        uid=derived(app.secret_key,session['principal']+':'+key)[:32]
        users=dict(session.get('users',{}))
        if uid not in users and len(users)>=12: return dict(error='This browser already owns 12 demo users'),409
        users[uid]=name.strip();session['users']=users
        return dict(user_id=uid,name=users[uid])

    @app.post('/api/session/admin')
    def admin_login():
        data=request.get_json(silent=True) or {}
        if not isinstance(data,dict): return dict(error='Expected a JSON object'),400
        supplied=data.get('password')
        if not isinstance(supplied,str) or not hmac.compare_digest(supplied,password):
            return dict(error='Invalid administrator password'),403
        session['admin']=True
        return dict(admin=True)

    @app.post('/api/session/logout')
    def logout():
        session.pop('admin',None)
        return dict(admin=False)

    @app.before_request
    def authorize():
        if not request.path.startswith('/api/'): return
        if request.path in ('/api/demo/context','/api/session'): return
        bearer=hmac.compare_digest(request.headers.get('Authorization',''),'Bearer '+operator)
        if request.method=='POST' and not bearer:
            supplied=request.headers.get('X-CSRF-Token','')
            if not session.get('csrf') or not hmac.compare_digest(supplied,session['csrf']):
                return jsonify(error='Refresh the page to establish a valid browser session'),403
        if request.path.startswith('/api/session/'):
            if not session.get('principal'): return jsonify(error='Browser session required'),401
            return
        if privileged(): return
        route=request.path.removeprefix('/api/')
        if request.method=='GET' and route in ('seats/health','payment/health'): return
        body=request.get_json(silent=True) or {}
        if not isinstance(body,dict): return jsonify(error='Expected a JSON object'),400
        if route=='waiting-room/status' and request.method=='GET': return
        if route=='waiting-room/queue' and request.method=='GET': return
        if route=='waiting-room/submit' and request.method=='POST':
            if isinstance(body.get('user_id'),str) and body['user_id'] in session.get('users',{}): return
        match=re.fullmatch(r'waiting-room/requests/([A-Za-z0-9_-]+)(/checkout|/cancel)?',route)
        if match and owned_party(match[1]):
            if request.method=='GET' and match[2] in (None,'/checkout'): return
            if request.method=='POST' and match[2]=='/cancel': return
        if request.method=='POST' and route in ('payment/payments','payment/checkouts/cancel'):
            rid=body.get('request_id')
            if isinstance(rid,str) and re.fullmatch(r'[A-Za-z0-9_-]+',rid):
                # Bind the supplied hold to the authoritative waiting-room allocation.
                party=owned_party(rid)
                if party and (party.get('allocation') or {}).get('hold_id')==body.get('hold_id'): return
        return jsonify(error='This operation requires an owned booking or administrator access'),403

    @app.after_request
    def protect_response(response):
        if request.path.startswith('/api/'):
            response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='same-origin'
        return response

    app.extensions['filter_customer_queue']=lambda data: data if privileged() else {
        **data,'requests':[p for p in data.get('requests',[]) if p.get('user_id') in session.get('users',{})]}
