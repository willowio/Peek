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

    def wait_for(self,text,timeout=15,*,start=0):
        deadline=time.monotonic()+timeout
        while text not in self.output[start:]:
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
    parser.add_argument('--wheel',required=True,type=Path);parser.add_argument('--report',type=Path)
    args=parser.parse_args();wheel=args.wheel.resolve();checksum=hashlib.sha256(wheel.read_bytes()).hexdigest()
    match=__import__('re').fullmatch(r'peekcli-(\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?)-py3-none-any\.whl',wheel.name)
    assert match,'Expected versioned Peek wheel';version=match[1];checks=[]
    def record(name):checks.append(name);print('PASS '+name,flush=True)
    with zipfile.ZipFile(wheel) as archive:
        names=archive.namelist();metadata='peekcli-'+version+'.dist-info/'
        assert all(name.startswith(('peekcli/',metadata)) for name in names)
        assert not any(any(part in name for part in ('__pycache__','.pyc','workflows.py','.checkpoints','/Users/','tests/','locales/','settings.py','i18n.py','gtfo.txt')) for name in names)
        assert archive.read(metadata+'entry_points.txt').decode().strip()=='[console_scripts]\npeek = peekcli.cli:main'
        assert archive.read('peekcli/wordmark.txt')==(ROOT/'src/peekcli/wordmark.txt').read_bytes()
        assert archive.read('peekcli/strings.py')==(ROOT/'src/peekcli/strings.py').read_bytes()
    record('versioned wheel, canonical artwork, one English string source and one executable')
    with tempfile.TemporaryDirectory(prefix='peek-install-check-') as temp:
        folder=Path(temp).resolve();home=folder/'home';home.mkdir()
        prefix=home/'.local/share/peek';bin_dir=home/'.local/bin';launcher=bin_dir/'peek'
        personal=home/'old-settings.json';personal.write_text('{personal config retained}')
        shell_profile=home/'.zshrc';shell_profile.write_text('# untouched\nexport KEEP_THIS=1\n');shell_before=shell_profile.read_bytes()
        browse=home/'Chosen Folder';browse.mkdir();(browse/'fixture-note.txt').write_text('ordinary fixture')
        nested=home/'Documents/Native Smoke/deep';nested.mkdir(parents=True);(nested/'native-needle-fixture.txt').write_text('native filename fixture')
        env=dict(os.environ,HOME=str(home),PATH=str(bin_dir)+':/usr/bin:/bin',TERM='xterm-256color',PEEK_CONFIG=str(personal),PEEK_LANG='ru',PYTHONPATH='/poisoned-pythonpath',PYTHONDONTWRITEBYTECODE='1')
        for key in ('NO_COLOR','PEEK_NO_MOTION','PEEK_REDUCED_MOTION','PYTHONHOME'):env.pop(key,None)
        def install():
            process=subprocess.run([sys.executable,str(ROOT/'scripts/install.py'),'--wheel',str(wheel),'--sha256',checksum],env=env,text=True,capture_output=True,timeout=120,cwd=folder)
            assert process.returncode==0,process.stdout+process.stderr
            assert 'Peek '+version+' installed.' in process.stdout and launcher.is_file() and os.access(launcher,os.X_OK)
            assert '\x1b' not in process.stdout+process.stderr and 'Installing peek' not in process.stdout+process.stderr
            assert shell_profile.read_bytes()==shell_before and personal.read_text()=='{personal config retained}'
            assert not (prefix/'bin/peekcli').exists() and str(ROOT) not in launcher.read_text()
        install();record('plain offline user-local install; real independent launcher; personal settings/profile untouched')
        # Report counts from unittest itself, including actual skips, not a stale constant.
        suite_code="""import json,sys,unittest
suite=unittest.defaultTestLoader.discover(sys.argv[1],top_level_dir=sys.argv[2])
r=unittest.TextTestRunner(verbosity=0).run(suite)
print(json.dumps({'run':r.testsRun,'failures':len(r.failures),'errors':len(r.errors),'skipped_count':len(r.skipped),'skipped':[{'test':t.id(),'reason':reason} for t,reason in r.skipped],'expected_failures':len(r.expectedFailures),'unexpected_successes':len(r.unexpectedSuccesses)}))
sys.exit(0 if r.wasSuccessful() else 1)
"""
        installed_tests=subprocess.run([str(prefix/'bin/python'),'-I','-B','-c',suite_code,str(ROOT/'tests'),str(ROOT)],env=env,cwd=folder,text=True,capture_output=True,timeout=90)
        assert installed_tests.returncode==0,installed_tests.stdout+installed_tests.stderr
        unit_tests=json.loads(installed_tests.stdout)
        record(f"complete installed suite: {unit_tests['run']} tests, {unit_tests['skipped_count']} skipped")
        for arguments in ([],['--version'],['--help'],['apps','--json'],['gtfo']):
            process=subprocess.run([str(launcher),*arguments],env=env,text=True,capture_output=True,timeout=15,cwd=folder)
            assert process.returncode==(1 if not arguments or arguments==['gtfo'] else 2),process.stderr
            assert process.stderr.strip() and prefix.exists()
        record('only peek/peek gtfo supported; non-TTY launch and removal fail clearly')
        session=Session(env)
        try:
            session.wait_for(b'\x1b[?1049h');session.send(b' ')
            session.wait_for(b'Applications')
            session.send(b'?');session.wait_for(b'Navigate');session.wait_for(b'Find & organize')
            assert b'Getting started' not in session.output and b'Launch Intro' not in session.output
            session.send(b'?');session.send(b'3');session.wait_for(b'Press / to find filenames')
            session.send(b'/native-needle\n');session.wait_for(b'native-needle-fixture.txt')
            session.send(b'\n');time.sleep(.15);mark=len(session.output);session.send(b'f');session.wait_for(b'Finder reveal requested.',start=mark)
            session.send(b'\x1b');session.send(b'\x1b');session.send(b'f');session.send(b'j'*6+b'\n');session.wait_for(b'Folder path:')
            session.send(os.fsencode(str(browse))+b'\n');session.send(b'/fixture-note\n');session.wait_for(b'fixture-note.txt')
            session.send(b'c');session.wait_for(b'Visible Results');session.send(b'\x1b')
            session.send(b'4');session.wait_for(b'FileVault');time.sleep(.15);session.send(b'\n');session.send(b'm');session.wait_for(b'Reference only');session.wait_for(b'Check status')
            session.send(b'\x1b');session.send(b'\x1b')
            for key in (b'5',b'6',b'1'):session.send(key);time.sleep(.10)
            session.send(b'q');code,output=session.finish();assert code==0,output[-1500:]
            assert str(launcher) in output
        finally:session.stop()
        record('fresh zsh: native nested/common/custom Files search, real Finder reveal, Security reference, six sections, Copy, Help and quit')
        # A normal key skips a static reduced-motion intro, rather than quitting.
        session=Session(dict(env,NO_COLOR='1'))
        try:
            session.wait_for(b'\x1b[?1049h');session.send(b'q');session.wait_for(b'Applications');session.send(b'q')
            code,_=session.finish();assert code==0
        finally:session.stop()
        record('NO_COLOR static intro consumes first q; next q exits normally')
        session=Session(env,columns=42,rows=10)
        try:
            session.wait_for(b'Peek needs a little more room.')
            session.send(b'q');code,_=session.finish();assert code==0
        finally:session.stop()
        record('small-window guidance and quit remain usable')
        def uninstall(answer,*,extra=None,tamper=False):
            session=Session(dict(env,**(extra or {})),' gtfo');original=launcher.read_bytes()
            try:
                session.wait_for(b'Remove Peek? [y/N] ')
                if tamper:launcher.write_bytes(original+b'# changed\n')
                session.send(answer);code,output=session.finish()
                assert '\x1b' not in output and ' *  .  +  ' not in output and ' .  |   . ' not in output
                return code,output
            finally:
                session.stop()
                if tamper:launcher.write_bytes(original)
        marker=(prefix/'.peek-install.json').read_bytes()
        for answer,label in [(b'N\n','N'),(b'\n','empty Enter'),(b'junk\nYY\nN\n','invalid/repeated then N')]:
            code,output=uninstall(answer);assert code==0 and 'Nothing removed' in output
            assert prefix.exists() and launcher.exists() and (prefix/'.peek-install.json').read_bytes()==marker
            record(label+' cancels with no deletion or animation')
        for answer,expected,label in [(b'\x04',0,'EOF'),(b'\x03',130,'Ctrl+C')]:
            code,output=uninstall(answer);assert code==expected and prefix.exists() and launcher.exists()
            record(label+' cancels without deletion')
        code,output=uninstall(b'Y\n',tamper=True)
        assert code==1 and prefix.exists() and launcher.exists() and 'launcher has changed' in output
        record('ownership change after confirmation refuses unrelated/changed content')
        code,output=uninstall(b'bad\ny\n',extra={'PEEK_NO_MOTION':'1'})
        assert code==0 and 'Peek removed' in output and not prefix.exists() and not launcher.exists()
        assert personal.exists() and shell_profile.read_bytes()==shell_before
        record('confirmed removal is plain and deletes only verified environment/launcher')
        # Pinned local bootstrap exercises strict dynamic ZIP/wheel identity without network hosting.
        import importlib.util
        spec=importlib.util.spec_from_file_location('peek_bootstrap',ROOT/'scripts/bootstrap.py');bootstrap=importlib.util.module_from_spec(spec);spec.loader.exec_module(bootstrap)
        bundle=wheel.parent/f'peek-{version}-install.zip';payload=bundle.read_bytes();previous=dict(os.environ)
        try:
            os.environ.update(env);code=bootstrap.install_bundle(payload,hashlib.sha256(payload).hexdigest())
        finally:os.environ.clear();os.environ.update(previous)
        assert code==0 and launcher.exists()
        code,_=uninstall(b'Y\n');assert code==0 and not prefix.exists() and not launcher.exists()
        record('version-aware verified bootstrap and clean reinstall after uninstall')
        prefix.mkdir(parents=True);sentinel=prefix/'keep';sentinel.write_text('untouched')
        failed=subprocess.run([sys.executable,str(ROOT/'scripts/install.py'),'--wheel',str(wheel),'--sha256',checksum],env=env,text=True,capture_output=True,timeout=30)
        assert failed.returncode==1 and sentinel.read_text()=='untouched'
        failed=subprocess.run([sys.executable,str(ROOT/'scripts/install.py'),'--wheel',str(wheel),'--sha256','0'*64,'--prefix',str(home/'bad-install')],env=env,text=True,capture_output=True,timeout=30)
        assert failed.returncode==1 and not (home/'bad-install').exists()
        record('existing target and checksum failure preserve unrelated data')
    report={'status':'passed','version':version,'checks':checks,'count':len(checks),'installed_tests':unit_tests,'wheel_sha256':checksum}
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(report,indent=2)+'\n')
    print(f'{len(checks)} disposable installation checks passed.')
    return 0


if __name__=='__main__':raise SystemExit(main())
