#!/usr/bin/env python3
"""Exercise a disposable installed Peek from fresh shells; never remove a development install."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import pty
import select
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
import fcntl
import zipfile

ROOT=Path(__file__).resolve().parents[1]


class Session:
    def __init__(self,env,args='',columns=100,rows=30):
        self.pid,self.fd=pty.fork();self.output=b'';self.closed=False
        if self.pid==0:
            os.chdir('/private/tmp' if Path('/private/tmp').exists() else '/tmp')
            os.execve('/bin/zsh',['zsh','-f','-c','command -v peek; exec peek'+args],env)
        fcntl.ioctl(self.fd,termios.TIOCSWINSZ,struct.pack('HHHH',rows,columns,0,0))

    def send(self,value):os.write(self.fd,value)

    def wait_for(self,text,timeout=15):
        deadline=time.monotonic()+timeout
        while text not in self.output:
            if time.monotonic()>deadline:raise AssertionError('Timed out waiting for '+repr(text)+'; tail='+repr(self.output[-1000:]))
            if select.select([self.fd],[],[],.05)[0]:
                try:chunk=os.read(self.fd,65536)
                except OSError:chunk=b''
                if not chunk:raise AssertionError('Peek exited before '+repr(text)+'; tail='+repr(self.output[-1000:]))
                self.output+=chunk
        return self.output

    def finish(self):
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            if select.select([self.fd],[],[],.05)[0]:
                try:chunk=os.read(self.fd,65536)
                except OSError:chunk=b''
                if chunk:self.output+=chunk
            pid,status=os.waitpid(self.pid,os.WNOHANG)
            if pid:
                os.close(self.fd);self.closed=True
                return os.waitstatus_to_exitcode(status),self.output.decode(errors='replace')
        self.stop();raise AssertionError('Installed Peek did not exit.')

    def stop(self):
        if self.closed:return
        try:os.kill(self.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        try:os.waitpid(self.pid,0)
        except ChildProcessError:pass
        os.close(self.fd);self.closed=True


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheel',required=True,type=Path)
    parser.add_argument('--report',type=Path)
    args=parser.parse_args();wheel=args.wheel.resolve()
    checksum=hashlib.sha256(wheel.read_bytes()).hexdigest();checks=[]
    def record(name):checks.append(name);print('PASS '+name,flush=True)
    with zipfile.ZipFile(wheel) as archive:
        names=archive.namelist()
        assert all(name.startswith(('peekcli/','peekcli-0.1.0.dist-info/')) for name in names)
        assert not any(any(part in name for part in ('__pycache__','.pyc','workflows.py','.checkpoints','/Users/','tests/')) for name in names)
        entry=archive.read('peekcli-0.1.0.dist-info/entry_points.txt').decode().strip()
        assert entry=='[console_scripts]\npeek = peekcli.cli:main'
        assert len([name for name in names if '/locales/' in name and name.endswith('.json')])==7
        assert archive.read('peekcli/wordmark.txt')==(ROOT/'src/peekcli/wordmark.txt').read_bytes()
        assert 'peekcli/gtfo.txt' not in names
        for source in (ROOT/'src/peekcli/locales').glob('*.json'):
            assert archive.read('peekcli/locales/'+source.name)==source.read_bytes()
    record('wheel contains only current runtime/assets, seven catalogs and one executable')
    with tempfile.TemporaryDirectory(prefix='peek-install-check-') as temp:
        folder=Path(temp).resolve();home=folder/'home';home.mkdir()
        prefix=home/'.local/share/peek';bin_dir=home/'.local/bin';launcher=bin_dir/'peek'
        config=home/'settings.json';config.write_text(json.dumps({'language':'en','intro':True}))
        shell_profile=home/'.zshrc';shell_profile.write_text('# untouched\nexport KEEP_THIS=1\n')
        shell_before=shell_profile.read_bytes()
        env=dict(os.environ,HOME=str(home),PATH=str(bin_dir)+':/usr/bin:/bin',TERM='xterm-256color',PEEK_CONFIG=str(config),PEEK_LANG='en',PYTHONPATH='/nonexistent/poisoned-pythonpath',PYTHONDONTWRITEBYTECODE='1')
        for key in ('NO_COLOR','PEEK_NO_MOTION','PEEK_REDUCED_MOTION','PYTHONHOME'):env.pop(key,None)
        def install(extra=()):
            process=subprocess.run([sys.executable,str(ROOT/'scripts/install.py'),'--wheel',str(wheel),'--sha256',checksum,*extra],env=env,text=True,capture_output=True,timeout=120,cwd=folder)
            assert process.returncode==0,process.stdout+process.stderr
            assert "run 'peek' to begin." in process.stdout and launcher.is_file() and os.access(launcher,os.X_OK)
            assert "✓ peek is ready.\n\ntake a look around.\nrun 'peek' to begin." in process.stdout
            assert 'Installing peek' not in process.stdout+process.stderr
            assert shell_profile.read_bytes()==shell_before
            assert not (prefix/'bin/peekcli').exists()
            assert str(ROOT) not in launcher.read_text()
            assert (prefix/'.peek-install.json').is_file()
        install();record('clean user-local offline installation; real launcher; no aliases or shell writes')
        installed_tests=subprocess.run([str(prefix/'bin/python'),'-I','-B','-m','unittest','discover','-s',str(ROOT/'tests'),'-t',str(ROOT),'-q'],env=env,cwd=folder,text=True,capture_output=True,timeout=60)
        assert installed_tests.returncode==0,installed_tests.stdout+installed_tests.stderr
        record('full unittest suite passes against the clean installed package')
        for arguments in ([],['--version'],['--help'],['apps','--json'],['gtfo']):
            process=subprocess.run([str(launcher),*arguments],env=env,text=True,capture_output=True,timeout=15,cwd=folder)
            assert process.returncode==(1 if not arguments or arguments==['gtfo'] else 2),process.stderr
            assert process.stderr.strip() and prefix.exists()
        record('non-TTY launch/uninstall and retired flags fail clearly without removal')
        # A fresh shell has no repository/venv/alias dependency; -I defeats poisoned PYTHONPATH.
        session=Session(env)
        try:
            session.wait_for(b'Applications');session.send(b',')
            session.wait_for(b'Launch Intro');assert b'Theme' not in session.output
            session.send(b'\x1b')
            for key in (b'2',b'3',b'4',b'5',b'1'):
                session.send(key);time.sleep(.12)
            session.send(b'?');session.wait_for(b'Getting started');session.send(b'R')
            time.sleep(.12);session.send(b' ');session.send(b'q')
            code,output=session.finish();assert code==0,output[-1000:]
            assert str(launcher) in output and 'Developer Tools' in output
        finally:session.stop()
        record('fresh zsh opens installed TUI, two settings, five sections, Help, intro replay and quit')
        # Small window retains a usable quit command and centered guidance.
        session=Session(env,columns=42,rows=10)
        try:
            session.wait_for(b'Peek needs a little more room.');session.send(b'q')
            code,_=session.finish();assert code==0
        finally:session.stop()
        record('small-window guidance and quit work in installed executable')
        def uninstall(answer,*,extra=None,interrupt_animation=False,tamper=False):
            session=Session(dict(env,**(extra or {})),' gtfo')
            original=launcher.read_bytes()
            try:
                session.wait_for(b'Remove Peek? [y/N] ')
                if tamper:launcher.write_bytes(original+b'# changed\n')
                session.send(answer)
                if interrupt_animation:
                    session.wait_for(b' .  |   . ');session.send(b'\x03')
                return session.finish()
            finally:
                session.stop()
                if tamper:launcher.write_bytes(original)
        marker=(prefix/'.peek-install.json').read_bytes()
        for answer,label in [(b'N\n','N'),(b'\n','empty Enter'),(b'junk\nYY\nN\n','invalid/repeated then N')]:
            code,output=uninstall(answer);assert code==0 and 'Nothing removed. See you around.' in output
            assert ' *  .  +  ' in output and prefix.exists() and launcher.exists()
            assert (prefix/'.peek-install.json').read_bytes()==marker
            record(label+' keeps all owned files and plays confetti')
        for answer,expected,label in [(b'\x04',0,'EOF'),(b'\x03',130,'Ctrl+C')]:
            code,output=uninstall(answer);assert code==expected and 'Nothing removed. See you around.' in output
            assert prefix.exists() and launcher.exists()
            record(label+' cancels without deletion')
        code,output=uninstall(b'N\n',extra={'PEEK_NO_MOTION':'1'})
        assert code==0 and ' *  .  +  ' not in output and prefix.exists();record('disabled-motion N keeps installation without animation')
        code,output=uninstall(b'Y\n',tamper=True)
        assert code==1 and prefix.exists() and launcher.exists() and 'launcher has changed' in output
        record('ownership change after confirmation refuses removal')
        # Confirmed Y remains effective when its optional rain is interrupted.
        code,output=uninstall(b'Y\n',interrupt_animation=True)
        assert code==0 and 'Peek removed. Thanks for taking a look.' in output and not prefix.exists() and not launcher.exists(),output
        assert config.exists() and shell_profile.read_bytes()==shell_before
        record('Y pixel rain, interrupted animation and actual owned removal; settings/profile retained')
        install()
        code,output=uninstall(b'bad\ny\n',extra={'PEEK_NO_MOTION':'1'})
        assert code==0 and ' .  |   . ' not in output and not prefix.exists() and not launcher.exists()
        record('invalid then y with disabled motion removes only confirmed owned installation')
        # Bootstrap verification is tested from the local pinned bundle, without inventing a URL.
        import importlib.util
        spec=importlib.util.spec_from_file_location('peek_bootstrap',ROOT/'scripts/bootstrap.py');bootstrap=importlib.util.module_from_spec(spec);spec.loader.exec_module(bootstrap)
        bundle=wheel.parent/'peek-0.1.0-install.zip';payload=bundle.read_bytes()
        previous=dict(os.environ)
        try:
            os.environ.update(env)
            result=bootstrap.install_bundle(payload,hashlib.sha256(payload).hexdigest())
        finally:os.environ.clear();os.environ.update(previous)
        assert result==0 and launcher.exists()
        code,output=uninstall(b'Y\n');assert code==0 and not prefix.exists() and not launcher.exists()
        record('pinned bootstrap bundle installs offline; ordinary Y rain and full removal succeed')
        # Default prefix collision must retain existing files; bad checksum never creates a prefix.
        prefix.mkdir(parents=True);sentinel=prefix/'keep';sentinel.write_text('untouched')
        failed=subprocess.run([sys.executable,str(ROOT/'scripts/install.py'),'--wheel',str(wheel),'--sha256',checksum],env=env,text=True,capture_output=True,timeout=30)
        assert failed.returncode==1 and sentinel.read_text()=='untouched'
        failed=subprocess.run([sys.executable,str(ROOT/'scripts/install.py'),'--wheel',str(wheel),'--sha256','0'*64,'--prefix',str(home/'bad-install')],env=env,text=True,capture_output=True,timeout=30)
        assert failed.returncode==1 and not (home/'bad-install').exists()
        record('existing target and checksum failure retain unrelated content')
    report={'status':'passed','checks':checks,'count':len(checks)}
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(report,indent=2)+'\n')
    print(f'{len(checks)} disposable installation checks passed.')
    return 0


if __name__=='__main__':raise SystemExit(main())
