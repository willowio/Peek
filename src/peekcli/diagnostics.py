"""Diagnostics use collector evidence without writing the clipboard or running repairs."""
from .models import Result
from .output import counts


def collect(results):
    rows=[]
    for result in results:
        rows.append({'name':result.collector, 'state':result.status, 'counts':counts(result),
                     'source':result.source, 'collected_at':result.collected_at, 'duration_ms':result.duration_ms,
                     'limitations':result.limitations, 'errors':result.errors})
    return Result('doctor','partial' if any(r.status!='ok' for r in results) else 'ok',rows,
                  source='Requested collection results', limitations=['No remediation or additional permission requests.'])
