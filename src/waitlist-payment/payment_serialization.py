"""JSON-safe public values shared by internal and customer HTTP adapters."""
from datetime import datetime
from uuid import UUID


def serializable(value):
    if isinstance(value,(UUID,datetime)):
        return value.isoformat() if isinstance(value,datetime) else str(value)
    if isinstance(value,dict):
        return {k:serializable(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):
        return [serializable(v) for v in value]
    return value
