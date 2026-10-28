from __future__ import annotations
import json
from .models import Result
from .text import safe
from .strings import text as tr

def counts(result: Result) -> dict:
    data = result.data
    if result.collector == 'brew':
        return {key: len(data.get(key, [])) for key in ('formulae', 'casks', 'taps')}
    if result.collector == 'services':
        return {'configured': len(data.get('launch_items', []))}
    if result.collector == 'apps':
        return {'identities': len(data), 'bundles': sum(len(r.get('locations') or [r.get('path')]) for r in data)}
    return {'items': len(data) if isinstance(data, list) else 1 if data else 0}


def item_report(item: dict | None) -> str:
    if not item:
        return 'No item selected.'
    lines = []
    for key, value in item.items():
        if key.startswith('_'):continue
        if key == 'tree' and isinstance(value, dict):
            lines.append(f"Bundle tree / {value.get('root', '.')} (depth {value.get('depth')}, limit {value.get('limit')}):")
            for entry in value.get('entries', []):
                lines.append(f"  {entry['path']}  [{entry['type']}]" + (f"  {entry['bytes']} bytes" if entry.get('bytes') is not None else ''))
            if value.get('truncated'):
                lines.append('  More entries exist; use e in app details to expand an inner directory.')
            continue
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, indent=2, default=str)
        elif value is None:
            value = 'Unavailable'
        elif isinstance(value, bool):
            value = 'Yes' if value else 'No'
        lines.append(f"{key.replace('_', ' ').capitalize()}: {value}")
    return safe('\n'.join(lines))


def human(result: Result, *, filter_text: str | None = None, verbose: bool = False, color: bool | None = None) -> str:
    from .views import records, select
    t=tr
    title=t('diagnostics' if result.collector=='doctor' else result.collector)
    status=t('scan_'+result.status)
    if result.collector=='files':
        state=result.context.get('state','idle')
        status=t({'idle':'file_not_searched','searching':'file_loading'}.get(state,'file_'+state))
    lines = [f"{title}  ·  {status}"]
    lines.append(' · '.join(f'{key}: {value}' for key, value in counts(result).items()))
    rows = select(result, query=filter_text) if filter_text else records(result)
    if result.collector in {'app', 'service'}:
        lines.append(item_report(result.data))
    elif result.collector == 'brew':
        for kind, label in [('formula', 'Formulae'), ('cask', 'Casks'), ('tap', 'Taps')]:
            group = [r for r in rows if r.get('kind') == kind]
            lines.append(f'\n{t(kind)} ({len(group)})')
            for row in group:
                lines.append(item_report(row) if verbose else f"  {row.get('name')}  {row.get('version') or ('local repository' if kind == 'tap' else 'version unavailable')}")
    else:
        for row in rows:
            if verbose:
                lines.extend(['', item_report(row)])
                continue
            name = row.get('name') or row.get('label') or 'Unnamed'
            if result.collector == 'apps':
                from .collectors.apps import source_of
                origin = t(source_of(row))
                lines.append(f"{name}  ·  {row.get('version') or 'version unavailable'}  ·  {origin}")
            elif result.collector == 'security':
                lines.append(f"{name:<15} {t(row.get('state','Unknown'))}")
            elif result.collector == 'services':
                lines.append(f"{name}  ·  {row.get('kind')}  ·  {t(row.get('state','Unknown'))}")
            elif result.collector == 'dev':
                lines.append(f"{name}  ·  {t(row.get('state','Unknown'))}  ·  {row.get('path') or row.get('value') or ''}")
            else:
                lines.append(item_report(row))
    if not rows and result.status == 'ok' and (result.collector!='files' or result.context.get('state') in {'empty','complete'}):
        lines.append('No matching entries.' if filter_text else 'No entries found.')
    lines.extend(f'Error: {e}' for e in result.errors)
    lines.extend(f'Coverage: {e}' for e in result.limitations)
    return safe('\n'.join(lines))

