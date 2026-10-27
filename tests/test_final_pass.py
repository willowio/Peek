import importlib.util
import json
import os
from pathlib import Path
import string
import tempfile
import unittest
from unittest.mock import patch
from peekcli import settings, tui, i18n
from peekcli.animation import Timeline
from peekcli.collectors import apps, dev
from peekcli.models import Result
from peekcli.screens import build_frame
from peekcli.system import Command
from peekcli.text import cell_width
from tests.test_peek import app_result


class PreferencesTests(unittest.TestCase):
    def test_roundtrip_atomic_save_and_corrupt_fallback(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'PEEK_CONFIG':temp+'/nested/settings.json'}):
            p,error=settings.load();self.assertFalse(error);self.assertFalse(settings.config_path().exists())
            p.language='pt_BR';settings.save(p)
            saved,error=settings.load();self.assertEqual(saved,p);self.assertFalse(error)
            self.assertEqual(settings.config_path().stat().st_mode&0o777,0o600)
            settings.config_path().write_text('{bad')
            saved,error=settings.load();self.assertTrue(error);self.assertEqual(saved,settings.Preferences())

    def test_invalid_values_do_not_become_preferences(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'PEEK_CONFIG':temp+'/settings.json'}):
            settings.config_path().write_text(json.dumps({'theme':[],'intro':'false','motion':'infinite','language':'xx','density':'compact'}))
            p,error=settings.load();self.assertTrue(error);self.assertTrue(p.intro);self.assertFalse(hasattr(p,'density'))

    def test_language_change_from_settings_persists_and_escape_returns_to_settings(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'PEEK_CONFIG':temp+'/settings.json'}):
            state=tui.State();noop=lambda *args:None
            tui._handle(state,',',noop,None);state.option=0;tui._handle(state,'\n',noop,None)
            self.assertEqual(state.overlay,'setting:language')
            state.option=2;tui._handle(state,'\n',noop,None)
            self.assertEqual(state.overlay,'settings');self.assertEqual(state.preferences.language,'pl')
            self.assertEqual(settings.load()[0].language,'pl')
            self.assertTrue(any('Ustawienia' in s.text for s in build_frame(state,100,30).spans))

    def test_failed_preference_save_keeps_previous_choice(self):
        state=tui.State();state.overlay='setting:language';state.options=[('pl','Polski')]
        with patch.object(tui,'save',side_effect=PermissionError('denied')):tui._handle(state,'\n',lambda *x:None,None)
        self.assertEqual(state.preferences.language,'auto');self.assertIn('could not',state.message)

    def test_environment_can_disable_animations(self):
        for variable in ('NO_COLOR','PEEK_NO_MOTION','PEEK_REDUCED_MOTION'):
            with patch.dict(os.environ,{'TERM':'xterm-256color',variable:'1'},clear=True):
                self.assertEqual(tui.animations_enabled(),False)


class LocalizationTests(unittest.TestCase):
    def test_all_advertised_catalogs_have_identical_keys_and_placeholders(self):
        base=i18n.catalog('en');self.assertGreater(len(base),100)
        def fields(value):return {name for _,name,_,_ in string.Formatter().parse(value) if name}
        for language in i18n.LANGUAGES:
            translated=i18n.catalog(language);self.assertEqual(set(translated),set(base),language)
            for key in base:self.assertEqual(fields(base[key]),fields(translated[key]),(language,key))

    def test_system_locale_and_english_fallback(self):
        for locale,expected in [('pl_PL.UTF-8','pl'),('ja_JP.UTF-8','en'),('pt_PT.UTF-8','pt_BR'),('xx_XX','en')]:
            with patch.dict(os.environ,{'LANG':locale},clear=True):self.assertEqual(i18n.resolve(),expected)
        self.assertEqual(i18n.tr('missing_key','pt_BR'),'missing_key')

    def test_every_language_and_screen_fits_all_terminal_sizes(self):
        for language in i18n.LANGUAGES:
            for width,height in [(60,15),(80,24),(120,30),(160,40)]:
                state=tui.State(preferences=settings.Preferences(language=language))
                state.results['apps']=app_result(20)
                state.results['apps'].data[0]['name']='世界e\u0301'+('long name '*30)
                for overlay in ('','help','settings','diagnostics','about','evidence','filter','setting:language'):
                    state.overlay=overlay;state.options=[('en','English'),('pt_BR','日本語')]
                    state.detail={'name':'世界','path':'/tmp/long path.app'} if overlay=='evidence' else None
                    frame=build_frame(state,width,height)
                    for span in frame.spans:
                        self.assertGreaterEqual(span.y,0);self.assertLess(span.y,height)
                        self.assertLessEqual(span.x+cell_width(span.text),width-1,(language,overlay,span))


class MotionAndLayoutTests(unittest.TestCase):
    def test_intro_timing_is_bounded_and_state_has_no_permanent_slogan(self):
        timeline=Timeline('intro','subtle',started=0)
        self.assertGreaterEqual(timeline.duration,1);self.assertLessEqual(timeline.duration,2)
        self.assertEqual(timeline.progress(clock=timeline.duration),1)
        state=tui.State();text='\n'.join(s.text for s in build_frame(state,120,30).spans)
        self.assertNotIn('take a look',text);self.assertNotIn('peek_',text)
        class Phase:
            kind='intro'
            def active(self):return True
            def progress(self):return .65
        state.effect=Phase()
        text='\n'.join(s.text for s in build_frame(state,120,30).spans)
        self.assertIn('take a look around.',text)

    def test_navigation_reaches_working_fifth_section(self):
        state=tui.State();scheduled=[]
        tui._handle(state,'5',lambda *args:scheduled.append(args),None)
        self.assertEqual(state.key,'dev');self.assertEqual(scheduled[0][0],'dev')

    def test_settings_are_not_a_primary_tab_and_modal_globals_do_not_edit_search(self):
        state=tui.State();self.assertEqual(len(tui.MENU),5)
        noop=lambda *x:None
        tui._handle(state,'/',noop,None)
        for c in ',15?':tui._handle(state,c,noop,None)
        self.assertEqual(state.view.query,',15?');self.assertEqual(state.overlay,'')

    def test_fixed_row_layout_and_density_is_not_a_preference(self):
        state=tui.State();state.results['apps']=app_result(100)
        self.assertFalse(hasattr(state.preferences,'density'))
        frame=build_frame(state,120,40)
        rows=[s.y for s in frame.spans if 'App ' in s.text and s.x==2]
        self.assertTrue(rows);self.assertTrue(all(b-a==1 for a,b in zip(rows,rows[1:])))

    def test_stale_signature_is_not_promoted_and_checked_signature_survives_tree_expansion(self):
        state=tui.State();state.detail={'name':'A','path':'/tmp/A.app','attribution':'verified_apple','signing':{'validation':'Valid at observation'}};state.detail_token=2
        tui._accept_result(state,'detail',1,Result('app','ok',{'attribution':'third_party'}))
        self.assertEqual(state.detail['attribution'],'verified_apple')
        tui._accept_result(state,'detail',2,Result('app','ok',{'signing':'Not checked','attribution':'unverified'}))
        self.assertEqual(state.detail['attribution'],'verified_apple')


class DeveloperAndAttributionTests(unittest.TestCase):
    def test_developer_collection_does_not_execute_discovered_binaries(self):
        with patch.object(dev,'find_executable',return_value='/tmp/do-not-run'),patch.object(dev,'run',return_value=Command(stdout='/Library/Developer/CommandLineTools')) as command,patch.object(dev.platform,'system',return_value='Darwin'),patch.dict(os.environ,{'PATH':'/missing:/missing:'}):
            result=dev.collect()
        self.assertEqual(command.call_args.args[0],['/usr/bin/xcode-select','-p'])
        groups={r['group'] for r in result.data};self.assertTrue({'environment','xcode','runtime','path_inspector','bundle_explorer','diagnostics'}<=groups)
        self.assertTrue(any(r.get('duplicate') for r in result.data))

    def test_bundle_id_claim_alone_never_becomes_verified_apple(self):
        import plistlib
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'A.app';(root/'Contents').mkdir(parents=True)
            (root/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'com.apple.fake'}))
            result=apps.inspect_bundle(str(root));self.assertEqual(result.data['attribution'],'unverified')
            with patch.object(apps.platform,'system',return_value='Darwin'),patch.object(apps,'run',side_effect=[Command(stderr='Authority=Fake'),Command(returncode=1,stderr='bad')]):
                result=apps.inspect_bundle(str(root),signing=True)
            self.assertEqual(result.data['attribution'],'unverified')

    def test_verified_apple_requires_apple_anchor(self):
        import plistlib
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'A.app';(root/'Contents').mkdir(parents=True)
            (root/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'org.fake'}))
            with patch.object(apps.platform,'system',return_value='Darwin'),patch.object(apps,'run',side_effect=[Command(stderr='Authority=Apple'),Command(),Command()]) as command:
                result=apps.inspect_bundle(str(root),signing=True)
            self.assertEqual(result.data['attribution'],'verified_apple')
            self.assertIn('anchor apple',command.call_args.args[0])



class InstallerTests(unittest.TestCase):
    def installer(self):
        spec=importlib.util.spec_from_file_location('peek_installer',Path(__file__).parents[1]/'scripts/install.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module



    def test_disabled_intro_replay_keeps_settings_open(self):
        state=tui.State();state.overlay='help'
        with patch.dict(os.environ,{'PEEK_NO_MOTION':'1'}):
            tui._handle(state,'R',lambda *x:None,None)
        self.assertEqual(state.overlay,'help');self.assertIn('Off',state.message)


class FinderTests(unittest.TestCase):
    def test_reveal_uses_only_native_finder_action_with_literal_path(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'$(never-execute).app';path.mkdir()
            with patch.object(tui.platform,'system',return_value='Darwin'),patch.object(tui,'run_command',return_value=Command()) as command:
                result=tui._reveal(str(path))
            self.assertEqual(result.status,'ok')
            self.assertEqual(command.call_args.args[0],['/usr/bin/open','-R',str(path)])
            self.assertEqual(command.call_args.kwargs['timeout'],3)

    def test_missing_finder_target_is_an_error_without_execution(self):
        with patch.object(tui.platform,'system',return_value='Darwin'),patch.object(tui,'run_command') as command:
            result=tui._reveal('/definitely-missing/peek-test.app')
        self.assertEqual(result.status,'error');command.assert_not_called()


if __name__=='__main__':unittest.main()
