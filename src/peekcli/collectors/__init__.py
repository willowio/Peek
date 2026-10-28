from . import apps, brew, security, services, dev, files
from ..models import Result
import time

COLLECTORS = {"apps": apps.collect, "brew": brew.collect, "files": files.idle, "security": security.collect, "services": services.collect, "dev": dev.collect}


def collect_all():
    results = []
    for name, collector in COLLECTORS.items():
        try:
            started=time.monotonic()
            result=collector()
            result.duration_ms=round((time.monotonic()-started)*1000,2)
            results.append(result)
        except Exception as exc:
            data = {'formulae': [], 'casks': [], 'taps': []} if name == 'brew' else {'launch_items': [], 'login_items': None} if name == 'services' else []
            results.append(Result(name, 'error', data, source='Collector failure', errors=[str(exc)]))
    return results
