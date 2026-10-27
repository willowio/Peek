"""GUI launch eligibility and safe dispatch without running fixture binaries."""
from contextlib import contextmanager
import io
import os
from pathlib import Path
import plistlib
import tempfile
import threading
import unittest
from unittest.mock import patch
from peekcli import launch,tui
from peekcli.models import Result
from peekcli.screens import context_keys,detail_lines
from peekcli.settings import Preferences
from peekcli.system import Command
from tests.test_distribution import script


class GuiOpenTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.darwin=patch.object(launch.platform,'system',return_value='Darwin');self.darwin.start();self.addCleanup(self.darwin.stop)

    def app(self,name='Editor ; $(never).app',**changes):
        app=self.root/name;(app/'Contents/MacOS').mkdir(parents=True)
        metadata={'CFBundleIdentifier':'org.example.editor','CFBundlePackageType':'APPL','CFBundleExecutable':'editor'};metadata.update(changes)
        (app/'Contents/Info.plist').write_bytes(plistlib.dumps(metadata))
        binary=app/'Contents/MacOS/editor';binary.write_bytes(b'\xcf\xfa\xed\xfe'+b'\0'*28);binary.chmod(0o755)
        return app

    def cask(self,app):
        package=self.root/'Caskroom/editor';(package/'1.0').mkdir(parents=True)
        link=package/'1.0'/app.name;link.symlink_to(app)
        return {'name':'editor','kind':'cask','path':str(package),'app_artifacts':[app.name],
                'applications':[{'path':str(app),'evidence':str(link)+' symlink'}]}

    def test_app_open_uses_only_absolute_native_open_and_literal_validated_bundle(self):
        app=self.app();row={'name':'Editor','path':str(app)}
        self.assertEqual(launch.launch_target(row,'apps'),str(app))
        with patch.object(launch,'run',return_value=Command()) as command:
            result=launch.open_app(row,'apps')
        self.assertEqual(result.status,'ok');command.assert_called_once_with(['/usr/bin/open',str(app)],timeout=5)

    def test_non_app_installer_background_and_loose_executables_never_dispatch(self):
        app=self.app()
        rows=[({'path':str(app)},'services'),({'path':str(app)},'dev'),({'path':str(app),'kind':'formula'},'brew')]
        for suffix in ('pkg','dmg','sh'):
            path=self.root/('Installer.'+suffix);path.write_text('never run');rows.append(({'path':str(path)},'apps'))
        for name,values in [('Background.app',{'LSBackgroundOnly':True}),('Installer.app',{'CFBundleIdentifier':'com.apple.installer'}),('Assistant.app',{'CFBundleIdentifier':'com.apple.InstallAssistant.Sequoia'}),('Library.app',{'CFBundlePackageType':'FMWK'}),('Package Handler.app',{'CFBundleDocumentTypes':[{'LSItemContentTypes':['com.apple.installer-package']}]})]:
            rows.append(({'path':str(self.app(name,**values))},'apps'))
        with patch.object(launch,'run') as command:
            for row,section in rows:
                with self.subTest(row=row):self.assertEqual(launch.open_app(row,section).status,'unavailable')
        command.assert_not_called()

    def test_malformed_missing_and_external_executables_or_metadata_are_rejected(self):
        app=self.app();row={'path':str(app)};info=app/'Contents/Info.plist';original=info.read_bytes()
        for payload in [b'bad plist',b'<?xml version="1.0"?><plist><bad>',b'<plist><array/></plist>']:
            info.write_bytes(payload);self.assertIsNone(launch.launch_target(row,'apps'))
        info.write_bytes(original)
        binary=app/'Contents/MacOS/editor';binary.write_text('#!/bin/sh\necho never');self.assertIsNone(launch.launch_target(row,'apps'))
        outside=self.root/'loose-binary';outside.write_bytes(b'\xcf\xfa\xed\xfe');outside.chmod(0o755)
        binary.unlink();binary.symlink_to(outside);self.assertIsNone(launch.launch_target(row,'apps'))
        info.unlink();outside_info=self.root/'outside.plist';outside_info.write_bytes(original);info.symlink_to(outside_info)
        self.assertIsNone(launch.launch_target(row,'apps'))
        self.assertIsNone(launch.launch_target({'path':str(self.root/'missing.app')},'apps'))

    def test_cask_requires_actual_declared_symlink_and_one_unambiguous_app(self):
        app=self.app();row=self.cask(app)
        self.assertEqual(launch.launch_target(row,'brew'),str(app))
        self.assertIsNone(launch.launch_target(dict(row,kind='formula'),'brew'))
        self.assertIsNone(launch.launch_target(dict(row,applications=[{'path':str(app)}]),'brew'))
        second=self.app('Second.app');package=Path(row['path']);link=package/'1.0'/second.name;link.symlink_to(second)
        row['app_artifacts'].append(second.name);row['applications'].append({'path':str(second),'evidence':str(link)+' symlink'})
        self.assertIsNone(launch.launch_target(row,'brew'))
        row['applications'].pop();first=package/'1.0'/app.name;first.unlink();first.symlink_to(second)
        self.assertIsNone(launch.launch_target(row,'brew'))

    def test_missing_after_selection_and_launch_error_leave_tui_usable(self):
        app=self.app();row={'name':'Editor','path':str(app)}
        state=tui.State(preferences=Preferences(language='en'));state.results['apps']=Result('apps','ok',[row]);state.detail=dict(row)
        jobs=[];tui._handle(state,'o',lambda *args:jobs.append(args),None)
        self.assertEqual(jobs[0][0],'launch');self.assertEqual(state.detail,row)
        app.rename(self.root/'Moved.app')
        with patch.object(launch,'run') as command:result=jobs[0][1]()
        command.assert_not_called();tui._accept_result(state,'launch',0,result)
        self.assertIn('No installed GUI app',state.message);self.assertEqual(state.detail,row)
        app=self.app('Another.app');row={'name':'Another','path':str(app)}
        with patch.object(launch,'run',return_value=Command(returncode=1,stderr='LaunchServices rejected it')):
            result=launch.open_app(row,'apps')
        tui._accept_result(state,'launch',0,result)
        self.assertEqual(result.status,'error');self.assertIn('Could not open',state.message);self.assertIn('LaunchServices',state.last_error)
        self.assertTrue(tui._handle(state,'\x1b',lambda *a:None,None));self.assertIsNone(state.detail)

    def test_shortcut_and_hints_only_for_eligible_selection_and_never_in_input_or_menus(self):
        app=self.app();row={'name':'Editor','path':str(app)}
        for section,data in [('apps',[row]),('brew',{'casks':[self.cask(app)]})]:
            state=tui.State();state.section=next(i for i,(_,key) in enumerate(tui.MENU) if key==section);state.results[section]=Result(section,'ok',data)
            self.assertIn(('o','open_app'),context_keys(state,'main'))
            self.assertTrue(any('o  ' in text for text,_ in detail_lines(state.rows()[0],section,state.t)))
            for detail in (None,dict(state.rows()[0])):
                state.detail=detail;jobs=[];tui._handle(state,'o',lambda *args:jobs.append(args),None);self.assertEqual(jobs[0][0],'launch')
            state.detail=None;state.search=True;jobs=[];tui._handle(state,'o',lambda *a:jobs.append(a),None)
            self.assertEqual(state.view.query,'o');self.assertFalse(jobs)
            state.search=False;state.overlay='settings';tui._handle(state,'o',lambda *a:jobs.append(a),None);self.assertFalse(jobs)
        state=tui.State();state.results['apps']=Result('apps','ok',[{'name':'Missing','path':str(self.root/'missing.app')}])
        self.assertNotIn('o',dict(context_keys(state,'main')))
        with patch.object(launch.platform,'system',return_value='Linux'):self.assertIsNone(launch.launch_target(row,'apps'))


class InstallerFeedbackTests(unittest.TestCase):
    def test_spinner_is_tty_only_and_cleans_up_after_errors(self):
        installer=script('install')
        class Terminal(io.StringIO):
            def isatty(self):return True
            def write(self,value):
                result=super().write(value);written.set();return result
        written=threading.Event();out=Terminal()
        with patch.dict(os.environ,{'TERM':'xterm-256color'},clear=True):
            with self.assertRaisesRegex(RuntimeError,'failure'):
                with installer.progress(out):
                    self.assertTrue(written.wait(1));raise RuntimeError('failure')
        self.assertIn('Installing peek',out.getvalue());self.assertTrue(out.getvalue().endswith('\r\x1b[2K'))
        for env,stream in [({'TERM':'xterm-256color'},io.StringIO()),({'TERM':'dumb'},Terminal()),({'TERM':'xterm-256color','PEEK_NO_MOTION':'1'},Terminal()),({'TERM':'xterm-256color','NO_COLOR':'1'},Terminal())]:
            with patch.dict(os.environ,env,clear=True),installer.progress(stream):pass
            self.assertEqual(stream.getvalue(),'')

    def test_success_requires_real_launcher_check(self):
        installer=script('install')
        with patch.object(installer.subprocess,'run',return_value=type('Process',(),{'returncode':1,'stderr':'Peek needs an interactive terminal.'})()) as command:
            installer.verify_launcher(Path('/owned/peek'))
            self.assertEqual(command.call_args.args[0],['/owned/peek'])
        for code,message in [(0,''),(2,'unsupported'),(1,'broken')]:
            with patch.object(installer.subprocess,'run',return_value=type('Process',(),{'returncode':code,'stderr':message})()):
                with self.assertRaises(RuntimeError):installer.verify_launcher(Path('/owned/peek'))
