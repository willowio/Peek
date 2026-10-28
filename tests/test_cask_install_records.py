"""Homebrew's moved-app layouts: receipt/config evidence without a staged symlink."""
import json
import os
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch
from peekcli import launch,tui,actions
from peekcli.collectors import brew
from peekcli.models import Result
from peekcli.system import Command


class CaskInstallRecordTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.appdir=self.root/'Applications';self.appdir.mkdir()
        self.prefix=self.root/'homebrew';self.package=self.prefix/'Caskroom/vendor-token'
        (self.package/'2.4.1').mkdir(parents=True);(self.package/'.metadata').mkdir()
        self.receipt=self.package/'.metadata/INSTALL_RECEIPT.json';self.config=self.package/'.metadata/config.json'
        self.platform=patch.object(launch.platform,'system',return_value='Darwin');self.platform.start();self.addCleanup(self.platform.stop)

    def app(self,path):
        (path/'Contents/MacOS').mkdir(parents=True)
        (path/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'org.example.gui','CFBundlePackageType':'APPL','CFBundleExecutable':'gui'}))
        binary=path/'Contents/MacOS/gui';binary.write_bytes(b'\xcf\xfa\xed\xfe'+b'\0'*28);binary.chmod(0o755)
        return path

    def record(self,artifacts,config=None):
        self.receipt.write_text(json.dumps({'source':{'version':'2.4.1','tap':'homebrew/cask'},'uninstall_artifacts':artifacts}))
        if config is not None:self.config.write_text(json.dumps(config))

    def collect(self):
        paths={'--prefix':self.prefix,'--cellar':self.prefix/'Cellar','--caskroom':self.prefix/'Caskroom','--repository':self.prefix}
        with patch.object(brew,'find_executable',return_value='/native/brew'),patch.object(brew,'run',side_effect=lambda args,**kw:Command(stdout=str(paths[args[1]]))) as commands:
            result=brew.collect()
        self.assertEqual(result.status,'ok');self.assertEqual(commands.call_count,4)
        self.assertTrue(all(args.args[0][1] in paths for args in commands.call_args_list))
        return result.data['casks'][0]

    def test_normal_applications_install_without_caskroom_symlink(self):
        app=self.app(self.appdir/'Actual Product.app')
        self.record([{'app':['Actual Product.app']}],{'default':{'appdir':'/Applications'},'env':{},'explicit':{}})
        # Redirect only the real standard directory, never write into /Applications.
        native_path=Path
        with patch.object(brew,'Path',side_effect=lambda value:native_path(self.appdir if str(value)=='/Applications' else value)):
            row=self.collect()
            self.assertEqual(launch.launch_target(row,'brew'),str(app))
            self.assertFalse((self.package/'2.4.1/Actual Product.app').exists())
            with patch.object(launch,'run',return_value=Command()) as command:
                self.assertEqual(launch.open_app(row,'brew').status,'ok')
            command.assert_called_once_with(['/usr/bin/open',str(app)],timeout=5)
            state=tui.State();state.section=1;state.results['brew']=actions.prepare_result(Result('brew','ok',{'casks':[row]}))
            jobs=[];tui._handle(state,'o',lambda *args:jobs.append(args),None)
            self.assertEqual(jobs[0][0],'launch')

    def test_default_appdir_works_without_saved_config_but_needs_receipt(self):
        app=self.app(self.appdir/'Recorded.app');self.record([{'app':['Recorded.app']}])
        native_path=Path
        with patch.object(brew,'Path',side_effect=lambda value:native_path(self.appdir if str(value)=='/Applications' else value)):
            row=self.collect();self.assertEqual(launch.launch_target(row,'brew'),str(app))
            self.receipt.unlink();self.assertIsNone(launch.launch_target(row,'brew'))

    def test_recorded_renamed_target_and_saved_config_precedence(self):
        explicit=self.root/'home/Personal Apps';app=self.app(explicit/'Friendly GUI.app')
        self.app(self.appdir/'Friendly GUI.app')
        self.record([{'app':['Payload/Nested Original.app',{'target':'Friendly GUI.app'}]}],
                    {'default':{'appdir':str(self.appdir)},'env':{'appdir':str(self.root/'Env Apps')},'explicit':{'appdir':'~/Personal Apps'}})
        with patch.dict(os.environ,{'HOME':str(self.root/'home')}):
            row=self.collect();self.assertEqual(launch.launch_target(row,'brew'),str(app))
        self.assertEqual(row['app_artifacts'],['Payload/Nested Original.app'])

    def test_dangling_staged_link_does_not_block_recorded_installed_target(self):
        app=self.app(self.appdir/'Recorded.app')
        (self.package/'2.4.1/Recorded.app').symlink_to(self.root/'missing.app')
        self.record([{'app':['Recorded.app']}],{'default':{'appdir':str(self.appdir)}})
        self.assertEqual(launch.launch_target(self.collect(),'brew'),str(app))

    def test_explicit_absolute_target_does_not_derive_a_name(self):
        app=self.app(self.root/'Custom Apps'/'Chosen Name.app')
        self.record([{'app':['Original.app',{'target':str(app)}]}])
        self.assertEqual(launch.launch_target(self.collect(),'brew'),str(app))

    def test_staged_bundles_installers_and_formulae_are_not_launch_targets(self):
        self.app(self.package/'2.4.1/Only Staged.app')
        self.app(self.appdir/'vendor-token.app')
        self.record([{'app':['Only Staged.app']},{'pkg':['Installer.pkg']},{'binary':['tool']}],{'default':{'appdir':str(self.appdir)}})
        row=self.collect()
        with patch.object(launch,'run') as command:
            self.assertEqual(launch.open_app(row,'brew').status,'unavailable')
            self.assertEqual(launch.open_app(dict(row,kind='formula'),'brew').status,'unavailable')
        command.assert_not_called()

    def test_multiple_apps_remain_ambiguous_and_missing_targets_fail_safely(self):
        first=self.app(self.appdir/'One.app');second=self.app(self.appdir/'Two.app')
        self.record([{'app':['One.app']},{'app':['Two.app']}],{'default':{'appdir':str(self.appdir)}})
        row=self.collect();self.assertIsNone(launch.launch_target(row,'brew'))
        second.rename(self.appdir/'Moved.app');self.assertEqual(launch.launch_target(row,'brew'),str(first))
        first.rename(self.appdir/'Gone.app')
        with patch.object(launch,'run') as command:self.assertEqual(launch.open_app(row,'brew').status,'unavailable')
        command.assert_not_called()

    def test_changed_receipts_and_malformed_config_cannot_authorize_cached_targets(self):
        self.app(self.appdir/'Recorded.app')
        self.record([{'app':['Recorded.app']}],{'default':{'appdir':str(self.appdir)}})
        row=self.collect();self.assertIsNotNone(launch.launch_target(row,'brew'))
        self.record([{'pkg':['Recorded.pkg']}],{'default':{'appdir':str(self.appdir)}})
        self.assertIsNone(launch.launch_target(row,'brew'))
        self.record([{'app':['Recorded.app']}]);self.config.write_text('{invalid')
        self.assertIsNone(launch.launch_target(row,'brew'))
        self.config.write_text(json.dumps({'default':{'appdir':str(self.appdir)},'explicit':{'appdir':17}}))
        self.assertIsNone(launch.launch_target(row,'brew'))
        self.record([{'app':['Recorded.app',{'target':'../Applications/Recorded.app'}]}],{'default':{'appdir':str(self.appdir)}})
        self.assertIsNone(launch.launch_target(row,'brew'))
