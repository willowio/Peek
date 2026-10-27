#!/usr/bin/env python3
"""Install a checksum-verified Peek wheel without modifying shell configuration."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import threading
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


@contextmanager
def progress(stream=None):
    stream=sys.stderr if stream is None else stream
    enabled=(stream.isatty() and 'NO_COLOR' not in os.environ
             and os.environ.get('PEEK_NO_MOTION')!='1' and os.environ.get('PEEK_REDUCED_MOTION')!='1'
             and os.environ.get('TERM','') not in {'','dumb'})
    if not enabled:
        yield
        return
    stopped=threading.Event()
    def spin():
        index=0
        try:
            while not stopped.is_set():
                stream.write('\rInstalling peek... '+'|/-\\'[index%4]);stream.flush();index+=1
                stopped.wait(.1)
        except OSError:pass
    worker=threading.Thread(target=spin,daemon=True);worker.start()
    try:yield
    finally:
        stopped.set();worker.join()
        try:stream.write('\r\x1b[2K');stream.flush()
        except OSError:pass


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


def validate_wheel(wheel,checksum):
    if len(checksum)!=64 or any(c not in '0123456789abcdef' for c in checksum.lower()):
        raise ValueError('Provide the trusted SHA-256 checksum (64 hexadecimal characters).')
    if hashlib.sha256(wheel.read_bytes()).hexdigest()!=checksum.lower():raise ValueError('Wheel checksum does not match. Nothing installed.')
    if wheel.stat().st_size>32_000_000:raise ValueError('Wheel is too large.')
    with zipfile.ZipFile(wheel) as archive:
        if len(archive.namelist())>5000 or sum(i.file_size for i in archive.infolist())>32_000_000:raise ValueError('Wheel is too large.')
        metadata=[name for name in archive.namelist() if name.endswith('.dist-info/METADATA')]
        entry=[name for name in archive.namelist() if name.endswith('.dist-info/entry_points.txt')]
        if len(metadata)!=1 or len(entry)!=1:raise ValueError('Invalid Peek wheel metadata.')
        text=archive.read(metadata[0]).decode()
        if '\nName: peekcli\n' not in '\n'+text or '\nVersion: 0.1.0\n' not in '\n'+text:raise ValueError('Expected the Peek v0.1.0 wheel.')
        if archive.read(entry[0]).decode().strip()!='[console_scripts]\npeek = peekcli.cli:main':raise ValueError('Wheel must expose only the peek command.')


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
        wheel=Path(staged.name)/'peekcli-0.1.0-py3-none-any.whl'
        wheel.write_bytes(source.read_bytes())
        validate_wheel(wheel,args.sha256)
        if prefix.exists() or prefix.is_symlink():raise ValueError('Installation directory already exists. Keep it or uninstall it explicitly first.')
        if launcher.exists() or launcher.is_symlink():raise ValueError('A peek launcher already exists here. Nothing was overwritten.')
        if prefix.is_relative_to(bin_dir) or bin_dir.is_relative_to(prefix):raise ValueError('Keep the environment and executable directories separate.')
        prefix.parent.mkdir(parents=True,exist_ok=True);bin_dir.mkdir(parents=True,exist_ok=True)
        if prefix.parent.resolve()!=prefix.parent or bin_dir.resolve()!=bin_dir:raise ValueError('Choose installation directories without symlinked parents.')
        if any(p.stat().st_uid!=os.getuid() or p.stat().st_mode&0o022 for p in (prefix.parent,bin_dir)):
            raise ValueError('Installation directories must be owned by you and not writable by others.')
        collision=shutil.which('peek')
        if collision and Path(collision).absolute()!=launcher:raise ValueError('Another peek command is on PATH: '+collision+'. Resolve it explicitly first.')
        with progress():
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
        mark='✓'
        try:mark.encode(getattr(sys.stdout,'encoding',None) or 'utf-8')
        except UnicodeError:mark='ok'
        print(mark+" peek is ready.\n\ntake a look around.\nrun 'peek' to begin.")
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
