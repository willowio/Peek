"""Validate the private installation inventory before removing any owned files."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys

MARKER='.peek-install.json'
SCHEMA=1


def fingerprint(path):
    info=path.lstat()
    if stat.S_ISLNK(info.st_mode):return {'link':os.readlink(path)}
    if stat.S_ISREG(info.st_mode):
        return {'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    if stat.S_ISDIR(info.st_mode):return {'directory':True}
    raise ValueError(f'Unsupported installation entry: {path}')


def inventory(prefix):
    """Do not follow directory symlinks, including the environment's Python links."""
    found={}
    for directory,dirs,files in os.walk(prefix,followlinks=False):
        for name in dirs+files:
            path=Path(directory)/name
            relative=path.relative_to(prefix).as_posix()
            if relative==MARKER:continue
            found[relative]=fingerprint(path)
    return found


def verify(prefix=None,package=None):
    prefix=Path(sys.prefix if prefix is None else prefix).absolute()
    package=Path(__file__ if package is None else package).resolve()
    if prefix.is_symlink() or prefix.resolve()!=prefix or prefix==Path(sys.base_prefix).resolve():
        raise ValueError('Automatic removal requires a verified isolated Peek installation.')
    if not (prefix/'pyvenv.cfg').is_file() or not package.is_relative_to(prefix):
        raise ValueError('This installation is unsupported. Use the tool that originally installed Peek.')
    marker=prefix/MARKER
    info=marker.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077 or info.st_size>2_000_000:
        raise ValueError('Peek ownership record is unsafe; refusing removal.')
    data=json.loads(marker.read_text())
    if not isinstance(data,dict):raise ValueError('Peek ownership record must be an object.')
    if (data.get('schema')!=SCHEMA or data.get('package')!='peekcli' or data.get('prefix')!=str(prefix)
            or not isinstance(data.get('id'),str) or len(data['id'])!=32):
        raise ValueError('Peek ownership record does not match this installation.')
    launcher=Path(data['launcher'])
    if (not launcher.is_absolute() or launcher.name!='peek' or launcher.parent.resolve()!=launcher.parent
            or launcher.is_relative_to(prefix) or launcher.is_symlink()):
        raise ValueError('Peek launcher path is unsafe; refusing removal.')
    if launcher.lstat().st_uid!=os.getuid() or fingerprint(launcher)!=data.get('launcher_record'):
        raise ValueError('Peek launcher has changed or is not owned by this installation.')
    if not shutil.rmtree.avoids_symlink_attacks:
        raise ValueError('Safe directory removal is not supported on this Python build.')
    expected=data.get('files')
    if not isinstance(expected,dict) or not expected or inventory(prefix)!=expected:
        raise ValueError('Installation files have changed; refusing to remove unverified content. Restore them or use the original installer.')
    return data


def remove(data):
    """Recheck ownership after confirmation; preserve settings and all other paths."""
    current=verify()
    if current!=data:raise ValueError('Installation changed after confirmation; nothing removed.')
    prefix=Path(current['prefix']);launcher=Path(current['launcher'])
    shutil.rmtree(prefix)
    # Recheck the launcher after directory removal as well.
    if launcher.is_symlink() or fingerprint(launcher)!=current['launcher_record']:
        raise ValueError('Environment removed; launcher changed and was retained.')
    launcher.unlink()
    if prefix.exists() or launcher.exists():raise OSError('Some owned installation files remain.')
