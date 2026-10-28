"""Public launch contract, removal decisions, and ownership/integrity boundaries."""
from contextlib import ExitStack, redirect_stdout, redirect_stderr
from dataclasses import asdict
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from peekcli import cli, installation, maintenance, animation, tui

ROOT=Path(__file__).resolve().parents[1]


def script(name):
    spec=importlib.util.spec_from_file_location('peek_'+name,ROOT/'scripts'/f'{name}.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


class LaunchContractTests(unittest.TestCase):
    def invoke(self,args):
        out,err=io.StringIO(),io.StringIO()
        with redirect_stdout(out),redirect_stderr(err):result=cli.main(args)
        return result,out.getvalue(),err.getvalue()

    def test_only_two_public_invocations(self):
        for args in [['--help'],['--version'],['apps'],['--json'],['--verbose'],['--filter','x'],['overview'],['settings'],['uninstall'],['brew','taps'],['gtfo','--preview'],['gtfo','yes']]:
            with self.subTest(args=args),patch('peekcli.tui.run') as run,patch('peekcli.maintenance.uninstall') as uninstall:
                code,out,err=self.invoke(args)
                self.assertEqual(code,2);self.assertFalse(out);self.assertIn('peek gtfo',err)
                run.assert_not_called();uninstall.assert_not_called()
        with patch('peekcli.tui.can_launch',return_value=True),patch('peekcli.tui.run') as run:
            self.assertEqual(self.invoke([])[0],0);run.assert_called_once_with()
        with patch('peekcli.maintenance.uninstall',return_value=7) as uninstall:
            self.assertEqual(self.invoke(['gtfo'])[0],7);uninstall.assert_called_once_with()

    def test_non_tty_and_terminal_failure_are_explained(self):
        with patch('peekcli.tui.can_launch',return_value=False),patch('peekcli.tui.run') as run:
            code,out,error=self.invoke([])
        self.assertEqual(code,1);self.assertFalse(out);self.assertIn('interactive terminal',error);run.assert_not_called()
        with patch('peekcli.tui.can_launch',return_value=True),patch('peekcli.tui.run',side_effect=tui.curses.error('unavailable')):
            self.assertIn('could not open',self.invoke([])[2])



class UninstallDecisionTests(unittest.TestCase):
    def exercise(self,answers,*,error=None,tty=True,verification_error=None):
        class Terminal(io.StringIO):
            def isatty(self):return tty
        out,err=Terminal(),io.StringIO();plan={'prefix':'/verified/peek','launcher':'/verified/bin/peek'}
        with ExitStack() as stack:
            stack.enter_context(patch('sys.stdin.isatty',return_value=tty));stack.enter_context(patch('sys.stdout',out));stack.enter_context(patch('sys.stderr',err))
            verify=stack.enter_context(patch.object(maintenance,'verify',return_value=plan,side_effect=verification_error))
            remove=stack.enter_context(patch.object(maintenance,'remove',side_effect=error));ask=stack.enter_context(patch('builtins.input',side_effect=answers))
            code=maintenance.uninstall()
        self.assertNotIn('\x1b',out.getvalue())
        return code,out.getvalue(),err.getvalue(),remove,ask,verify

    def test_confirmed_y_removes_verified_installation_without_animation(self):
        code,out,err,remove,ask,_=self.exercise(['Y'])
        self.assertEqual(code,0);remove.assert_called_once();self.assertIn('Peek removed',out)
        self.assertFalse(hasattr(animation,'animate_terminal'))

    def test_n_and_default_cancel_without_removal(self):
        for answer in ['N','n','','  n  ']:
            code,out,err,remove,ask,_=self.exercise([answer]);self.assertEqual(code,0)
            remove.assert_not_called();self.assertIn('Nothing removed',out)

    def test_invalid_repeated_input_never_confirms(self):
        code,out,err,remove,ask,_=self.exercise(['yes','YY','maybe','N'])
        self.assertEqual(code,0);self.assertEqual(ask.call_count,4);remove.assert_not_called()
        code,out,err,remove,ask,_=self.exercise(['invalid','y'])
        self.assertEqual(code,0);remove.assert_called_once()

    def test_eof_and_prompt_interrupt_cancel_safely(self):
        for interruption,expected in [(EOFError(),0),(KeyboardInterrupt(),130)]:
            code,out,err,remove,ask,_=self.exercise([interruption]);self.assertEqual(code,expected);remove.assert_not_called()

    def test_removal_failure_never_prints_success(self):
        code,out,err,remove,ask,_=self.exercise(['Y'],error=PermissionError('denied'))
        self.assertEqual(code,1);self.assertIn('denied',err);self.assertNotIn('Peek removed',out)

    def test_non_tty_and_unverified_installations_refuse_before_prompt(self):
        code,out,err,remove,ask,verify=self.exercise([],tty=False)
        self.assertEqual(code,1);verify.assert_not_called();ask.assert_not_called();remove.assert_not_called()
        code,out,err,remove,ask,_=self.exercise([],verification_error=ValueError('unsupported'))
        self.assertEqual(code,1);self.assertIn('unsupported',err);ask.assert_not_called();remove.assert_not_called()


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name).resolve();self.prefix=self.base/'environment';self.prefix.mkdir()
        self.package=self.prefix/'lib/peekcli/installation.py';self.package.parent.mkdir(parents=True);self.package.write_text('# fixture')
        (self.prefix/'pyvenv.cfg').write_text('fixture')
        self.launcher=self.base/'bin/peek';self.launcher.parent.mkdir();self.launcher.write_text('owned launcher')
        self.data={'schema':1,'package':'peekcli','prefix':str(self.prefix),'launcher':str(self.launcher),'id':'a'*32,'files':installation.inventory(self.prefix),'launcher_record':installation.fingerprint(self.launcher)}
        self.marker=self.prefix/installation.MARKER;self.marker.write_text(json.dumps(self.data));self.marker.chmod(0o600)

    def verify(self):return installation.verify(self.prefix,self.package)

    def test_inventory_verifies_links_without_following_them(self):
        self.assertEqual(self.verify(),self.data)
        link=self.prefix/'outside';link.symlink_to(self.base)
        self.data['files']=installation.inventory(self.prefix);self.assertEqual(self.data['files']['outside'],{'link':str(self.base)})
        self.marker.write_text(json.dumps(self.data));self.assertEqual(self.verify(),self.data)

    def test_foreign_or_modified_content_blocks_removal(self):
        (self.prefix/'unrelated.txt').write_text('keep')
        with self.assertRaisesRegex(ValueError,'unverified'):self.verify()
        (self.prefix/'unrelated.txt').unlink();self.launcher.write_text('different command')
        with self.assertRaisesRegex(ValueError,'changed'):self.verify()

    def test_symlinked_launcher_marker_or_prefix_and_loose_marker_refuse(self):
        self.launcher.unlink();self.launcher.symlink_to(self.package)
        with self.assertRaises(ValueError):self.verify()
        self.launcher.unlink();self.launcher.write_text('owned launcher');self.marker.chmod(0o644)
        with self.assertRaises(ValueError):self.verify()
        self.marker.chmod(0o600);link=self.base/'alias';link.symlink_to(self.prefix)
        with self.assertRaises(ValueError):installation.verify(link,self.package)

    def test_removal_revalidates_and_preserves_other_files(self):
        foreign=self.base/'keep';foreign.write_text('keep')
        with patch.object(installation,'verify',return_value=self.data):installation.remove(self.data)
        self.assertFalse(self.prefix.exists());self.assertFalse(self.launcher.exists());self.assertEqual(foreign.read_text(),'keep')

    def test_malformed_or_missing_ownership_record_is_refused(self):
        self.marker.write_text('[]')
        with self.assertRaises(ValueError):self.verify()
        self.marker.unlink()
        with self.assertRaises(OSError):self.verify()

    def test_ownership_change_after_confirmation_aborts(self):
        with patch.object(installation,'verify',return_value=dict(self.data,id='b'*32)),patch.object(installation.shutil,'rmtree') as remove:
            with self.assertRaises(ValueError):installation.remove(self.data)
        remove.assert_not_called();self.assertTrue(self.launcher.exists())


class ArtifactTests(unittest.TestCase):
    def test_bootstrap_rejects_bad_checksum_and_unexpected_archive_before_execution(self):
        bootstrap=script('bootstrap');buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as archive:archive.writestr('../escape','never')
        payload=buffer.getvalue()
        with patch.object(bootstrap.subprocess,'call') as execute:
            with self.assertRaises(ValueError):bootstrap.install_bundle(payload,'0'*64)
            with self.assertRaises(ValueError):bootstrap.install_bundle(payload,hashlib.sha256(payload).hexdigest())
        execute.assert_not_called()
        for url in ['http://example.invalid/bundle','file:///tmp/bundle','https://user:pass@example.invalid/bundle']:
            with self.assertRaises(ValueError):bootstrap.https_url(url)

    def test_installer_requires_checksum_and_exact_public_entrypoint(self):
        installer=script('install')
        with tempfile.TemporaryDirectory() as temp:
            wheel=Path(temp)/'peekcli-0.2.0-py3-none-any.whl'
            with zipfile.ZipFile(wheel,'w') as archive:
                archive.writestr('peekcli/__init__.py',"__version__ = '0.2.0'\n")
                archive.writestr('peekcli-0.2.0.dist-info/METADATA','Name: peekcli\nVersion: 0.2.0\n')
                archive.writestr('peekcli-0.2.0.dist-info/entry_points.txt','[console_scripts]\npeek = peekcli.cli:main\n')
            installer.validate_wheel(wheel,hashlib.sha256(wheel.read_bytes()).hexdigest())
            with self.assertRaises(ValueError):installer.validate_wheel(wheel,'0'*64)
            with zipfile.ZipFile(wheel,'a') as archive:archive.writestr('other.dist-info/entry_points.txt','[console_scripts]\npeekcli = peekcli.cli:main\n')
            with self.assertRaises(ValueError):installer.validate_wheel(wheel,hashlib.sha256(wheel.read_bytes()).hexdigest())
