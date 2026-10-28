#!/usr/bin/env python3
"""Install a checksum-verified Peek wheel without modifying shell configuration."""
from __future__ import annotations
import argparse
import ast
import re
from email.parser import Parser
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile


def verify_launcher(launcher):
    result=subprocess.run([str(launcher)],stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=10)
    if result.returncode!=1 or 'interactive terminal' not in result.stderr:
        raise RuntimeError('The installed peek executable did not pass its launch check.')


def command(args):
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',PIP_CONFIG_FILE=os.devnull)
    env.pop('PYTHONPATH',None);env.pop('PYTHONHOME',None)
    result=subprocess.run([str(x) for x in args],capture_output=True,text=True,timeout=120,env=env)
    if result.returncode:raise RuntimeError(result.stderr.strip() or result.stdout.strip() or 'Installation command failed.')
    return result.stdout.strip()


WHEEL_NAME=re.compile(r'peekcli-(\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?)-py3-none-any\.whl')


def validate_wheel(wheel,checksum):
    if len(checksum)!=64 or any(c not in '0123456789abcdef' for c in checksum.lower()):
        raise ValueError('Provide the trusted SHA-256 checksum (64 hexadecimal characters).')
    if wheel.stat().st_size>32_000_000:raise ValueError('Wheel is too large.')
    if hashlib.sha256(wheel.read_bytes()).hexdigest()!=checksum.lower():raise ValueError('Wheel checksum does not match. Nothing installed.')
    match=WHEEL_NAME.fullmatch(wheel.name)
    if not match:raise ValueError('Expected a versioned peekcli Python wheel.')
    version=match[1];metadata_dir='peekcli-'+version+'.dist-info/'
    with zipfile.ZipFile(wheel) as archive:
        names=archive.namelist()
        if len(names)>5000 or len(names)!=len(set(names)) or sum(i.file_size for i in archive.infolist())>32_000_000:raise ValueError('Invalid or oversized wheel.')
        for info in archive.infolist():
            name=info.filename
            if (not name.startswith(('peekcli/',metadata_dir)) or '..' in Path(name).parts or '\\' in name
                    or (info.external_attr>>16)&0o170000==0o120000):
                raise ValueError('Unexpected wheel contents.')
        metadata=[name for name in names if name.endswith('.dist-info/METADATA')]
        entry=[name for name in names if name.endswith('.dist-info/entry_points.txt')]
        if metadata!=[metadata_dir+'METADATA'] or entry!=[metadata_dir+'entry_points.txt']:raise ValueError('Invalid Peek wheel metadata.')
        headers=Parser().parsestr(archive.read(metadata[0]).decode())
        if headers.get_all('Name')!=['peekcli'] or headers.get_all('Version')!=[version]:raise ValueError('Package identity/version mismatch.')
        if archive.read(entry[0]).decode().strip()!='[console_scripts]\npeek = peekcli.cli:main':raise ValueError('Wheel must expose only the peek command.')
        if 'peekcli/__init__.py' not in names:raise ValueError('Missing package runtime version.')
        try:tree=ast.parse(archive.read('peekcli/__init__.py').decode())
        except SyntaxError as exc:raise ValueError('Invalid package runtime version.') from exc
        versions=[node.value.value for node in tree.body if isinstance(node,ast.Assign) and isinstance(node.value,ast.Constant) and any(isinstance(target,ast.Name) and target.id=='__version__' for target in node.targets)]
        if versions!=[version]:raise ValueError('Package runtime version does not match wheel metadata.')
    return version


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheel',required=True,type=Path)
    parser.add_argument('--sha256',required=True)
    parser.add_argument('--prefix',type=Path,default=Path.home()/'.local/share/peek')
    parser.add_argument('--bin-dir',type=Path,default=Path.home()/'.local/bin')
    args=parser.parse_args(argv)
    if sys.version_info<(3,11):parser.error('Python 3.11 or newer is required.')
    prefix=args.prefix.expanduser().absolute();bin_dir=args.bin_dir.expanduser().absolute();launcher=bin_dir/'peek'
    created=False;installed_launcher=False;launcher_bytes=b''
    try:
        if hasattr(os,'geteuid') and os.geteuid()==0:raise ValueError('Install as your normal user; do not use sudo.')
        import curses  # Fail before writing if this interpreter cannot run the TUI.
        source=args.wheel.expanduser().resolve()
        if source.stat().st_size>32_000_000:raise ValueError('Wheel is too large.')
        staged=tempfile.TemporaryDirectory(prefix='peek-wheel-')
        wheel=Path(staged.name)/source.name
        wheel.write_bytes(source.read_bytes())
        version=validate_wheel(wheel,args.sha256)
        if prefix.exists() or prefix.is_symlink():raise ValueError('Installation directory already exists. Keep it or uninstall it explicitly first.')
        if launcher.exists() or launcher.is_symlink():raise ValueError('A peek launcher already exists here. Nothing was overwritten.')
        if prefix.is_relative_to(bin_dir) or bin_dir.is_relative_to(prefix):raise ValueError('Keep the environment and executable directories separate.')
        prefix.parent.mkdir(parents=True,exist_ok=True);bin_dir.mkdir(parents=True,exist_ok=True)
        if prefix.parent.resolve()!=prefix.parent or bin_dir.resolve()!=bin_dir:raise ValueError('Choose installation directories without symlinked parents.')
        if any(p.stat().st_uid!=os.getuid() or p.stat().st_mode&0o022 for p in (prefix.parent,bin_dir)):
            raise ValueError('Installation directories must be owned by you and not writable by others.')
        collision=shutil.which('peek')
        if collision and Path(collision).absolute()!=launcher:raise ValueError('Another peek command is on PATH: '+collision+'. Resolve it explicitly first.')
        prefix.mkdir(mode=0o700);created=True
        command([sys.executable,'-m','venv',prefix])
        python=prefix/'bin/python'
        command([python,'-I','-m','pip','--isolated','install','--no-index','--no-deps','--no-cache-dir',wheel])
        installation_id=uuid.uuid4().hex
        launcher_bytes=('#!/bin/sh\n# Peek installation '+installation_id+'\nexec '+shlex.quote(str(python))+' -I -B -m peekcli "$@"\n').encode()
        # Atomic no-overwrite publication; hard linking fails if a target appeared.
        fd,name=tempfile.mkstemp(prefix='.peek-',dir=bin_dir)
        try:
            with os.fdopen(fd,'wb') as stream:stream.write(launcher_bytes);stream.flush();os.fsync(stream.fileno())
            os.chmod(name,0o755);os.link(name,launcher);installed_launcher=True
        finally:Path(name).unlink(missing_ok=True)
        metadata=json.loads(command([python,'-I','-B','-c',"import json,sys;from peekcli.installation import inventory,fingerprint;from peekcli import __version__;print(json.dumps({'files':inventory(__import__('pathlib').Path(sys.prefix)),'launcher_record':fingerprint(__import__('pathlib').Path(sys.argv[1])),'version':__version__}))",launcher]))
        metadata.update(schema=1,package='peekcli',prefix=str(prefix),launcher=str(launcher),id=installation_id)
        marker=prefix/'.peek-install.json'
        with marker.open('x') as stream:json.dump(metadata,stream,sort_keys=True);stream.write('\n')
        marker.chmod(0o600)
        command([python,'-I','-B','-c','from peekcli.installation import verify;verify()'])
        verify_launcher(launcher)
        if str(bin_dir) not in os.environ.get('PATH','').split(os.pathsep):
            print('Add this directory to PATH before running peek:')
            print('  export PATH='+shlex.quote(str(bin_dir))+':"$PATH"')
            print('Add that line to your shell profile if you want it in future terminals.')
        print('Executable: '+str(launcher))
        print('Shell configuration was not changed. Remove with: peek gtfo')
        print('Peek '+version+' installed. Run: peek')
        return 0
    except (OSError,ValueError,RuntimeError,ImportError,subprocess.SubprocessError,zipfile.BadZipFile,KeyboardInterrupt) as exc:
        # Only this attempt's freshly created paths are eligible for rollback.
        if installed_launcher and launcher.is_file() and launcher.read_bytes()==launcher_bytes:launcher.unlink()
        if created:shutil.rmtree(prefix)
        print('Peek installation stopped: '+str(exc),file=sys.stderr)
        return 130 if isinstance(exc,KeyboardInterrupt) else 1
    finally:
        if 'staged' in locals():staged.cleanup()


if __name__=='__main__':raise SystemExit(main())
