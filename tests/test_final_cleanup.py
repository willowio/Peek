from dataclasses import asdict
import json
import os
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch
from peekcli import tui
from peekcli.collectors import apps
from peekcli.screens import build_frame,footer
from peekcli.text import cell_width


class FinalNavigationTests(unittest.TestCase):
    def test_escape_returns_one_level_and_restores_detail_scroll(self):
        s=tui.State();s.detail={'name':'Example'};s.detail_scroll=7
        tui._open(s,'copy',[('selected','Selected Item')]);tui._open(s,'help')
        tui._handle(s,'\x1b',lambda *a:None,None);self.assertEqual(s.overlay,'copy')
        tui._handle(s,'\x1b',lambda *a:None,None);self.assertEqual(s.overlay,'');self.assertEqual(s.detail_scroll,7)
        tui._handle(s,'\x1b',lambda *a:None,None);self.assertIsNone(s.detail)
        self.assertFalse(tui._handle(s,'q',lambda *a:None,None))


    def test_sections_switch_directly_from_every_non_input_view(self):
        for overlay in ['','help','filter','sort','copy','evidence','bundle','diagnostics']:
            for key in '123456':
                s=tui.State();s.detail={'name':'Example'};s.detail_token=4;tui._open(s,'copy');tui._open(s,overlay)
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
