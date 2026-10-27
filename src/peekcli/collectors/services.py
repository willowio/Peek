from __future__ import annotations

import os
import plistlib
import platform
import re
from pathlib import Path
from typing import Any
from xml.parsers.expat import ExpatError
from ..models import Result, now
from ..system import run


def parse_plist(path: Path, kind: str) -> dict[str, Any] | None:
    try:
        if path.stat().st_size > 4 * 1024 * 1024:
            return None
        with path.open('rb') as stream:
            value = plistlib.load(stream)
    except (OSError, ValueError, plistlib.InvalidFileException, ExpatError, TypeError):
        return None
    if not isinstance(value, dict):
        return None
    args = value.get('ProgramArguments')
    label = value.get('Label')
    return {'label': label if isinstance(label, str) and label else path.stem, 'path': str(path), 'kind': kind,
            'program': value.get('Program') or (args[0] if isinstance(args, list) and args else None),
            'configured': True, 'configured_disabled': value.get('Disabled'), 'run_at_load': value.get('RunAtLoad'),
            'keep_alive': value.get('KeepAlive'), 'loaded': None, 'running': None, 'disabled': None,
            'state': 'Configured; active state unknown'}


def parse_list(raw: str) -> dict[str, dict]:
    lines = raw.splitlines()
    if not lines or lines[0].split() != ['PID', 'Status', 'Label']:
        raise ValueError('Unrecognized launchctl list header')
    result = {}
    for line in lines[1:]:
        parts = line.split(None, 2)
        if len(parts) != 3 or not re.fullmatch(r'-|[0-9]+', parts[0]) or not re.fullmatch(r'-?[0-9]+', parts[1]):
            raise ValueError('Unrecognized launchctl list row')
        pid, status, label = parts
        result[label] = {'pid': int(pid) if pid != '-' else None, 'last_exit_status': int(status),
                         'loaded': True, 'running': pid != '-'}
    return result


def inspect_service(item: dict) -> Result:
    domain = 'system' if 'Daemon' in item.get('kind', '') else f'gui/{os.getuid()}'
    target = domain + '/' + str(item['label'])
    command = run(['/bin/launchctl', 'print', target], timeout=5)
    data = dict(item, requested_domain=domain, evidence=command.stdout or command.stderr,
                observed_at=now(), source=f'launchctl print {target}')
    errors = []
    if command.error or command.returncode:
        data['state'] = 'Inaccessible or not visible in requested domain'
        errors.append(command.error or f'launchctl exited {command.returncode}: {command.stderr.strip()}')
    else:
        state = re.search(r'^\s*state = ([a-z ]+)\s*$', command.stdout, re.M)
        pid = re.search(r'^\s*pid = (\d+)\s*$', command.stdout, re.M)
        data['loaded'] = True
        data['running'] = True if pid and int(pid[1]) > 0 else False if state and state[1] in {'waiting', 'not running', 'exited'} else None
        data['state'] = 'Running' if data['running'] else 'Loaded' if data['running'] is False else 'Loaded; running unknown'
        if not state:
            errors.append('Unrecognized launchctl print state; raw evidence preserved')
    disabled = run(['/bin/launchctl', 'print-disabled', domain], timeout=5)
    if not disabled.error and disabled.returncode == 0:
        for label, flag in re.findall(r'^\s*"([^"\n]+)"\s*=>\s*(true|false)\s*$', disabled.stdout, re.M):
            if label == item['label']:
                data['disabled'] = flag == 'true'
                data['disabled_source'] = f'launchctl print-disabled {domain}'
                break
    else:
        errors.append(disabled.error or f'print-disabled {domain} exited {disabled.returncode}')
    return Result('service', 'partial' if errors else 'ok', data, source=f'launchctl print {target}', errors=errors,
                  limitations=['launchctl print output is not a stable API; missing fields remain unknown.', 'Observation is limited to this domain and collection time.'])


def collect(home: Path | None = None, roots: list[tuple[Path, str]] | None = None) -> Result:
    if platform.system() != 'Darwin':
        return Result('services', 'unavailable', {'login_items': None, 'launch_items': []}, source='launchd', limitations=['Requires macOS.'])
    home = home or Path.home()
    roots = roots if roots is not None else [(home / 'Library/LaunchAgents', 'User Launch Agent'),
            (Path('/Library/LaunchAgents'), 'System Launch Agent'), (Path('/Library/LaunchDaemons'), 'System Launch Daemon'),
            (Path('/System/Library/LaunchAgents'), 'Apple Launch Agent'), (Path('/System/Library/LaunchDaemons'), 'Apple Launch Daemon')]
    items, errors = [], []
    for root, kind in roots:
        try:
            paths = sorted(root.iterdir())
        except FileNotFoundError:
            continue
        except OSError as exc:
            errors.append(f'{root}: {exc}')
            continue
        for path in paths[:10000]:
            if path.suffix != '.plist':
                continue
            item = parse_plist(path, kind)
            if item:
                items.append(item)
            else:
                errors.append(f'Could not parse launchd property list: {path}')
        if len(paths) > 10000:
            errors.append(f'Entry limit reached: {root}')
    listing = run(['/bin/launchctl', 'list'], timeout=5)
    observed = {}
    if listing.error or listing.returncode:
        errors.append(listing.error or f'launchctl list exited {listing.returncode}: {listing.stderr.strip() or "no diagnostic; calling domain inaccessible"}')
    else:
        try:
            observed = parse_list(listing.stdout)
        except ValueError as exc:
            errors.append(str(exc))
    for item in items:
        if 'Daemon' not in item['kind'] and item['label'] in observed:
            item.update(observed[item['label']])
            item['state'] = 'Running' if item['running'] else 'Loaded'
            item['state_scope'] = 'Calling launchd domain, matched by label; not system-wide'
    items.sort(key=lambda x: (x['kind'], x['label'].casefold(), x['path']))
    return Result('services', 'partial', {'login_items': None, 'launch_items': items}, source='Launchd plists; launchctl list in calling domain', errors=errors,
                  limitations=['Configured plists do not prove a job is loaded or running. Absent labels remain unknown.',
                               'Loaded/running observations from list cover only the calling domain. Enter inspects one service domain.',
                               'The plist Disabled key is configuration, not an observed launchd override; disabled state remains unknown.',
                               'Login/background items are unavailable; no administrator authorization is requested.'])
