"""Shared section filtering, sorting and complete report/copy scopes."""
from dataclasses import replace
import json
from .collectors.apps import ownership_of, source_of
from .models import Result
from .text import safe
from .i18n import tr

LABELS = {'apps': 'Applications', 'brew': 'Homebrew', 'security': 'Security', 'services': 'Services & Startup', 'dev': 'Developer Tools'}
FILTERS = {'apps': [('all', 'All applications'), ('apple', 'Apple (declared)'), ('non_apple', 'Non-Apple (declared)')],
           'brew': [('all', 'All packages & taps'), ('formula', 'Formulae'), ('cask', 'Casks'), ('tap', 'Taps'), ('requested', 'Requested formulae')],
           'security': [('all', 'All controls'), ('Enabled', 'Enabled'), ('Disabled', 'Disabled')],
           'services': [('all', 'All configured items'), ('user', 'User agents'), ('system', 'System / Apple items'), ('running', 'Observed running'), ('loaded', 'Observed loaded'), ('daemon', 'Daemons')],
           'dev': [('all','All'), ('environment','Environment'), ('xcode','Xcode & Command Line Tools'), ('runtime','Runtimes & package tools'), ('path_inspector','PATH Inspector'), ('bundle_explorer','App Bundle Explorer'), ('diagnostics','Diagnostics')]}


def records(result: Result) -> list[dict]:
    if result.collector == 'brew':
        rows = []
        for group, kind in [('formulae', 'formula'), ('casks', 'cask'), ('taps', 'tap')]:
            rows.extend(dict(x, kind=kind) if isinstance(x, dict) else {'name': x, 'kind': kind} for x in result.data.get(group, []))
        return rows
    if result.collector == 'services':
        return result.data.get('launch_items', [])
    if isinstance(result.data, list):
        return result.data
    return [result.data] if result.data else []


def select(result: Result, *, group='all', query='', sort='name') -> list[dict]:
    rows = records(result)
    def matches(row):
        if query and query.casefold() not in json.dumps(row, ensure_ascii=False, default=str).casefold():
            return False
        if group == 'all':
            return True
        if result.collector == 'apps':
            if group in {'apple', 'third_party', 'unknown'}:
                return source_of(row) == group
            if group in {'verified_apple', 'unverified'}:
                return row.get('attribution', 'unverified') == group
            return ownership_of(row) == group
        if result.collector == 'brew':
            if group in {'requested', 'dependency'}:
                return row.get('kind') == 'formula' and row.get(group) is True
            return row.get('kind') == group
        if result.collector == 'security':
            return row.get('state') not in {'Enabled', 'Disabled'} if group == 'unknown' else row.get('state') == group
        if result.collector == 'dev':
            return row.get('group') == group
        if group == 'daemon':
            return 'Daemon' in row.get('kind', '')
        if group == 'user':
            return row.get('kind') == 'User Launch Agent'
        if group == 'system':
            return row.get('kind') in {'System Launch Agent', 'Apple Launch Agent'}
        if group == 'unknown':
            return row.get('loaded') is None
        return row.get(group) is True
    rows = [r for r in rows if matches(r)]
    field = {'name': 'name', 'version': 'version', 'kind': 'kind', 'state': 'state'}.get(sort, 'name')
    return sorted(rows, key=lambda r: (str(r.get(field) or r.get('label') or r.get('name') or '').casefold(), str(r.get('path', ''))))


def scoped(result: Result, rows: list[dict], label: str = '') -> Result:
    if result.collector == 'brew':
        data = {k: [r for r in rows if r.get('kind') == kind] for k, kind in [('formulae', 'formula'), ('casks', 'cask'), ('taps', 'tap')]}
    elif result.collector == 'services':
        data = dict(result.data, launch_items=rows)
    else:
        data = rows
    return replace(result, data=data, limitations=[*result.limitations, *([f'Filtered scope: {label}'] if label else [])])


def copy_scopes(result: Result) -> list[tuple[str, str]]:
    choices = [('all', f'Full {LABELS.get(result.collector, result.collector)} report')]
    choices.extend((key, label) for key, label in FILTERS[result.collector][1:])
    return choices + [('current', 'Current filtered results'), ('selected', 'Selected item details')]


def copy_report(result: Result, scope: str, *, current: list[dict], selected: dict | None, format: str = 'report', translate=tr) -> str:
    from .output import human, item_report
    if scope == 'selected' and format == 'report':
        return item_report(selected) if selected else 'No selected item.'
    rows = ([selected] if selected else []) if scope == 'selected' else current if scope == 'current' else select(result, group=scope)
    if result.collector == 'brew' and scope in {'requested', 'dependency'}:
        formulas = [r for r in records(result) if r.get('kind') == 'formula']
        if formulas and not any(isinstance(r.get(scope), bool) for r in formulas):
            return 'Requested/dependency classification is unavailable in the local receipts.'
    if format in {'names','summary'}:
        lines=[]
        for row in rows:
            name=row.get('name') or row.get('label') or translate('unknown')
            value=None
            if format=='summary':
                if result.collector in {'apps','brew'}:
                    value=row.get('version')
                    if not value and row.get('kind')!='tap':value=translate('version_missing')
                else:
                    status='running' if row.get('running') is True else 'loaded' if row.get('loaded') is True else row.get('state') or 'unknown'
                    value=translate(status)
            lines.append(str(name)+(f'  {value}' if value else ''))
        return safe('\n'.join(lines))
    return human(scoped(result, rows, scope if scope != 'all' else ''), color=False, verbose=True)
