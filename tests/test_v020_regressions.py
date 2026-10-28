import hashlib
import io
import json
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from peekcli import maintenance
from peekcli.collectors import apps,security
from peekcli.system import Command
from tests.test_distribution import script


class CollectorRefinementTests(unittest.TestCase):
    def test_filevault_off_busy_and_failures_use_documented_exit_codes(self):
        cases=[('FileVault is Off.',1,'Disabled'),('FileVault is On but Busy.',2,'Enabled'),('Permission denied',1,'Error'),('FileVault is On.',15,'Error')]
        for text,code,expected in cases:
            with patch.object(security,'find_executable',return_value='/fdesetup'),patch.object(security,'run',return_value=Command(stdout=text,returncode=code)):
                row=security.check('FileVault',['fdesetup','status'],('filevault is on',),('filevault is off',))
            self.assertEqual(row['state'],expected)
            if code==2:self.assertTrue(row['busy'])

    def test_firewall_subpolicies_are_contextualized_by_main_control(self):
        def check(name,*args):return {'name':name,'state':'Disabled' if name=='Firewall' else 'Enabled','explanation':'specific','limitation':'specific'}
        with patch.object(security.platform,'system',return_value='Darwin'),patch.object(security,'check',side_effect=check):r=security.collect()
        self.assertEqual(len(r.data),6)
        for row in r.data:
            self.assertIn('manage',row)
            if row['name'].startswith('Firewall '):self.assertIn('inactive',row['interpretation']);self.assertEqual(row['state'],'Enabled')

    def test_core_services_is_a_bounded_parent_root(self):
        roots=apps.app_roots(Path('/test-home'))
        self.assertIn(Path('/System/Library/CoreServices'),roots)
        self.assertNotIn(Path('/System/Library/CoreServices/Applications'),roots)

    def test_recorded_custom_cask_bundle_is_discovered_without_crawling_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'Custom Destination/Recorded.app';(path/'Contents').mkdir(parents=True)
            (path/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleName':'Recorded','CFBundleIdentifier':'org.example.recorded'}))
            with patch.object(apps.platform,'system',return_value='Darwin'),patch.object(apps,'app_roots',return_value=[]),patch.object(apps,'distribution_sources',return_value={str(path):'Homebrew installation record'}):
                result=apps.collect()
            self.assertEqual(len(result.data),1);self.assertEqual(result.data[0]['path'],str(path))


class VersionAndRemovalTests(unittest.TestCase):
    def wheel(self,root,version='0.3.12',runtime=None,extra=()):
        wheel=root/f'peekcli-{version}-py3-none-any.whl'
        with zipfile.ZipFile(wheel,'w') as archive:
            archive.writestr('peekcli/__init__.py',f'__version__ = {repr(runtime or version)}\n')
            archive.writestr(f'peekcli-{version}.dist-info/METADATA',f'Name: peekcli\nVersion: {version}\n')
            archive.writestr(f'peekcli-{version}.dist-info/entry_points.txt','[console_scripts]\npeek = peekcli.cli:main\n')
            for name in extra:archive.writestr(name,'unrelated')
        return wheel

    def test_installer_is_version_aware_but_rejects_mismatched_runtime_or_extra_paths(self):
        installer=script('install')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);wheel=self.wheel(root)
            self.assertEqual(installer.validate_wheel(wheel,hashlib.sha256(wheel.read_bytes()).hexdigest()),'0.3.12')
            for runtime,extra in [('0.2.0',()),(None,('../escape',)),(None,('foreign-package/file.py',))]:
                wheel=self.wheel(root,runtime=runtime,extra=extra)
                with self.assertRaises(ValueError):installer.validate_wheel(wheel,hashlib.sha256(wheel.read_bytes()).hexdigest())

    def test_bootstrap_rejects_two_wheels_or_extra_installation_members(self):
        bootstrap=script('bootstrap')
        for names in [('install.py','peekcli-0.2.0-py3-none-any.whl','peekcli-0.3.0-py3-none-any.whl'),('install.py','peekcli-0.2.0-py3-none-any.whl','extra.py')]:
            stream=io.BytesIO()
            with zipfile.ZipFile(stream,'w') as archive:
                for name in names:archive.writestr(name,'never execute')
            payload=stream.getvalue()
            with patch.object(bootstrap.subprocess,'call') as run:
                with self.assertRaises(ValueError):bootstrap.install_bundle(payload,hashlib.sha256(payload).hexdigest())
            run.assert_not_called()

    def test_interruption_after_confirmed_removal_reports_possible_partial_removal(self):
        out,err=io.StringIO(),io.StringIO()
        with patch('sys.stdin.isatty',return_value=True),patch('sys.stdout',out),patch('sys.stdout.isatty',return_value=True),patch('sys.stderr',err),patch.object(maintenance,'verify',return_value={'prefix':'/owned','launcher':'/bin/peek'}),patch('builtins.input',return_value='y'),patch.object(maintenance,'remove',side_effect=KeyboardInterrupt):
            self.assertEqual(maintenance.uninstall(),130)
        self.assertIn('partly removed',err.getvalue());self.assertNotIn('Nothing removed',out.getvalue());self.assertNotIn('Peek removed',out.getvalue())
