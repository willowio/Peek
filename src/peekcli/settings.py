"""Small user-owned preferences; loading never creates or modifies a file."""
from __future__ import annotations
from dataclasses import asdict, dataclass, fields
import json
import os
from pathlib import Path
import tempfile

CHOICES = {'language': ('auto', 'en', 'pl', 'de', 'fr', 'es', 'pt_BR', 'ru')}

@dataclass
class Preferences:
    language: str = 'auto'
    intro: bool = True


def config_path() -> Path:
    override = os.environ.get('PEEK_CONFIG')
    if override:
        return Path(override).expanduser()
    base = Path(os.environ['XDG_CONFIG_HOME']) / 'peek' if os.environ.get('XDG_CONFIG_HOME') else Path.home() / 'Library/Application Support/Peek'
    return base / 'settings.json'


def load() -> tuple[Preferences, str]:
    preferences = Preferences()
    try:
        path = config_path()
        if not path.exists():
            return preferences, ''
        if path.stat().st_size > 16384:
            raise ValueError('settings exceed 16 KiB')
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise ValueError('settings must be an object')
        if data.get('language') in ('it','ja'):data['language']='auto'
        invalid = []
        for f in fields(preferences):
            if f.name not in data:
                continue
            value = data[f.name]
            if f.name == 'intro' and isinstance(value, bool) or f.name in CHOICES and value in CHOICES[f.name]:
                setattr(preferences, f.name, value)
            else:
                invalid.append(f.name)
        return preferences, ('Invalid settings ignored: ' + ', '.join(invalid)) if invalid else ''
    except (OSError, ValueError, TypeError) as exc:
        return preferences, str(exc)


def save(preferences: Preferences):
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.settings-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(asdict(preferences), stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)

