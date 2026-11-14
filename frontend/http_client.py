"""Thread-local upstream pools; browser cookies never enter a shared session."""
from threading import local
import requests

_clients = local()


def transport_error_types(error):
    """Diagnose nested socket failures without logging URLs, headers or bodies."""
    pending=[error];seen=set();names=[]
    while pending and len(names)<16:
        current=pending.pop()
        if not isinstance(current,BaseException) or id(current) in seen:continue
        seen.add(id(current));names.append(type(current).__name__)
        pending.extend(arg for arg in current.args if isinstance(arg,BaseException))
        pending.extend((current.__cause__,current.__context__))
    return '/'.join(names)


def proxy_request(*args, **kwargs):
    session = getattr(_clients, 'session', None)
    if session is None:
        session = requests.Session()
        _clients.session = session
    # Never retain upstream Set-Cookie state across independent browser requests.
    session.cookies.clear()
    try:
        return session.request(*args, **kwargs)
    finally:
        session.cookies.clear()
