from dataclasses import asdict
import json
import os
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch
from peekcli import settings,tui,i18n
from peekcli.collectors import apps
from peekcli.screens import build_frame,footer
from peekcli.text import cell_width


class FinalNavigationTests(unittest.TestCase):
    def test_escape_returns_one_level_and_restores_detail_scroll(self):
        s=tui.State();s.detail={'name':'Example'};s.detail_scroll=7
        tui._open(s,'settings');s.option=0
        tui._handle(s,'\n',lambda *a:None,None)
        self.assertEqual(s.overlay,'setting:language')
        tui._handle(s,'\x1b',lambda *a:None,None)
        self.assertEqual((s.overlay,s.option),('settings',0))
        tui._handle(s,'\x1b',lambda *a:None,None)
        self.assertEqual(s.overlay,'');self.assertEqual(s.detail_scroll,7)
        tui._handle(s,'\x1b',lambda *a:None,None);self.assertIsNone(s.detail)
        self.assertFalse(tui._handle(s,'q',lambda *a:None,None))

    def test_setting_shortcut_does_not_stack_duplicate_settings(self):
        s=tui.State();noop=lambda *a:None
        for key in [',','\n',',']:tui._handle(s,key,noop,None)
        self.assertEqual(s.overlay,'settings')
        tui._handle(s,'\x1b',noop,None)
        self.assertEqual(s.overlay,'');self.assertFalse(s.overlay_stack)
        self.assertFalse(tui._handle(s,'q',noop,None))

    def test_sections_switch_directly_from_every_non_input_view(self):
        for overlay in ['','settings','setting:language','help','filter','sort','copy','evidence','bundle','diagnostics','about']:
            for key in '12345':
                s=tui.State();s.detail={'name':'Example'};s.detail_token=4;tui._open(s,'settings');tui._open(s,overlay)
                jobs=[];self.assertTrue(tui._handle(s,key,lambda *a:jobs.append(a),None))
                self.assertEqual(s.section,int(key)-1);self.assertEqual(s.overlay,'');self.assertFalse(s.overlay_stack);self.assertIsNone(s.detail);self.assertGreater(s.detail_token,4)
                self.assertFalse(tui._handle(s,'q',lambda *a:None,None))

    def test_search_and_path_inputs_keep_navigation_keys_as_text(self):
        s=tui.State();s.search=True
        for key in '15q,':tui._handle(s,key,lambda *a:None,None)
        self.assertEqual(s.view.query,'15q,');self.assertEqual(s.section,0)
        class Input:
            def __init__(self):self.keys=iter('15q\n')
            def timeout(self,*a):pass
            def getmaxyx(self):return 24,80
            def move(self,*a):pass
            def clrtoeol(self):pass
            def addstr(self,*a):pass
            def refresh(self):pass
            def get_wch(self):return next(self.keys)
        self.assertEqual(tui._read_query(Input()),'15q')

    def test_removed_preferences_and_languages_migrate_safely(self):
        self.assertEqual(set(i18n.LANGUAGES),{'en','pl','de','fr','es','pt_BR','ru'})
        self.assertNotIn('density',asdict(settings.Preferences()));self.assertNotIn('density',settings.CHOICES)
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'PEEK_CONFIG':temp+'/settings.json'}):
            p=Path(temp)/'settings.json'
            for language in ['it','ja']:
                original=json.dumps({'language':language,'density':'compact','motion':'off','intro':False});p.write_text(original)
                prefs,error=settings.load();self.assertFalse(error);self.assertEqual(prefs.language,'auto');self.assertFalse(hasattr(prefs,'motion'));self.assertFalse(prefs.intro);self.assertEqual(p.read_text(),original)
                self.assertEqual(i18n.catalog(language),i18n.catalog('en'))
                settings.save(prefs);self.assertNotIn('density',json.loads(p.read_text()));self.assertNotIn('motion',json.loads(p.read_text()))

    def test_russian_is_available_detected_and_persisted(self):
        self.assertEqual(i18n.LANGUAGES['ru'],'Русский')
        self.assertIn('ru',settings.CHOICES['language'])
        with patch.dict(os.environ,{'LC_ALL':'ru_RU.UTF-8'},clear=True):self.assertEqual(i18n.resolve(),'ru')
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'PEEK_CONFIG':temp+'/settings.json'}):
            settings.save(settings.Preferences(language='ru'))
            prefs,error=settings.load();self.assertFalse(error);self.assertEqual(prefs.language,'ru')
            self.assertEqual(i18n.tr('settings',prefs.language),'Настройки')

    def test_final_localized_views_and_hints_fit(self):
        for lang in i18n.LANGUAGES:
            for width,height in [(60,15),(80,18),(100,28),(160,40)]:
                s=tui.State(preferences=settings.Preferences(language=lang))
                for overlay in ['settings','setting:language','help','bundle','evidence','diagnostics']:
                    s.overlay=overlay;s.options=[('en','English')]
                    for span in build_frame(s,width,height).spans:self.assertLess(span.x+cell_width(span.text),width)
                    self.assertLessEqual(cell_width(footer(s,width-4)),width-4)


class TraversalCleanupTests(unittest.TestCase):
    def make_app(self,path):
        (path/'Contents').mkdir(parents=True)
        (path/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleName':'Boundary','CFBundleIdentifier':'org.example.boundary'}))

    def collect(self,roots):
        with patch.object(apps.platform,'system',return_value='Darwin'),patch.object(apps,'distribution_sources',return_value={}):return apps.collect(roots=roots)

    def test_immediate_app_at_depth_boundary_is_collected_before_limit(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);parent=root.joinpath(*['level'+str(i) for i in range(apps.DISCOVERY_DEPTH)])
            self.make_app(parent/'Boundary.app')
            r=self.collect([root]);self.assertEqual(len(r.data),1);self.assertEqual(r.status,'ok');self.assertFalse(r.errors)

    def test_real_depth_limit_stays_visible_and_symlink_subtrees_are_not_followed(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'root';root.mkdir();outside=Path(temp)/'outside';self.make_app(outside/'Other.app')
            parent=root.joinpath(*['level'+str(i) for i in range(apps.DISCOVERY_DEPTH)]);parent.mkdir(parents=True)
            (parent/'external').symlink_to(outside,target_is_directory=True)
            r=self.collect([root]);self.assertFalse(r.data);self.assertFalse(r.errors)
            (parent/'deeper').mkdir();self.make_app(parent/'deeper/Hidden.app')
            r=self.collect([root]);self.assertFalse(r.data);self.assertTrue(any('Traversal limit' in e for e in r.errors))

    def test_repeated_roots_do_not_duplicate_app_parsing(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.make_app(root/'Boundary.app')
            with patch.object(apps,'parse_app',wraps=apps.parse_app) as parse:
                r=self.collect([root,root])
            self.assertEqual(len(r.data),1);self.assertEqual(parse.call_count,1)
