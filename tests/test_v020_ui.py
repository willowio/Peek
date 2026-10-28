import csv
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from peekcli import tui,actions
from peekcli.animation import Timeline
from peekcli.collectors import files
from peekcli.models import Result
from peekcli.screens import build_frame,footer
from peekcli.text import cell_width
from peekcli.views import copy_report,sort_options


class NewUiTests(unittest.TestCase):
    def test_six_numeric_sections_lazy_loading_and_preserved_views(self):
        state=tui.State();jobs=[]
        self.assertEqual([key for _,key in state.menu],['apps','brew','files','security','services','dev'])
        state.view.query='keep';state.view.sort='version';state.view.selected=4
        for key in '23456':tui._handle(state,key,lambda *a:jobs.append(a),None)
        self.assertEqual(state.key,'dev');self.assertNotIn('files',[job[0] for job in jobs])
        tui._handle(state,'1',lambda *a:None,None);self.assertEqual(state.view.query,'keep');self.assertEqual(state.view.selected,4)

    def test_controls_only_help_fits_ordinary_window_and_returns_to_exact_context(self):
        state=tui.State();state.detail={'name':'Selected'};state.detail_scroll=7
        tui._handle(state,'?',lambda *a:None,None)
        text='\n'.join(span.text for span in build_frame(state,80,24).spans)
        for label in ['Navigate','Find & organize','Inspect & use','Other','Names / summary / TSV']:self.assertIn(label,text)
        self.assertNotIn('Getting started',text);self.assertNotIn('Settings',text);self.assertFalse(hasattr(state,'help_topic'))
        tui._handle(state,'?',lambda *a:None,None);self.assertEqual(state.overlay,'');self.assertEqual(state.detail_scroll,7)
        self.assertEqual(state.detail['name'],'Selected')

    def test_help_scrolls_same_reference_and_bounds_all_frames(self):
        for width,height in [(60,15),(80,24),(100,28),(160,40),(35,9)]:
            state=tui.State();state.overlay='help'
            for _ in range(30):tui._handle(state,tui.curses.KEY_DOWN,lambda *a:None,None)
            frame=build_frame(state,width,height)
            self.assertTrue(frame.spans)
            for span in frame.spans:
                self.assertTrue(0<=span.y<height);self.assertLessEqual(span.x+cell_width(span.text),width-1)
            self.assertIn('?',footer(state,max(1,width-4)))

    def test_intro_consumes_skip_including_quit_enter_and_section_keys(self):
        for key in ('q','3','\n','/','?'):
            state=tui.State();state.effect=Timeline('intro');jobs=[]
            self.assertTrue(tui._handle(state,key,lambda *a:jobs.append(a),None));self.assertEqual(state.section,0)
            self.assertIsNone(state.detail);self.assertEqual(state.overlay,'');self.assertFalse(state.search);self.assertFalse(jobs)
        state=tui.State();state.intro_static=True;self.assertTrue(tui._handle(state,'q',lambda *a:None,None));self.assertFalse(state.intro_static)
        state=tui.State();state.effect=Timeline('intro',started=0);self.assertFalse(tui._handle(state,'q',lambda *a:None,None))

    def test_files_input_is_literal_generational_and_stale_results_are_rejected(self):
        state=tui.State();tui._handle(state,'3',lambda *a:None,None);tui._handle(state,'/',lambda *a:None,None)
        for key in '6q?-live':tui._handle(state,key,lambda *a:self.fail('must not collect'),None)
        self.assertEqual(state.key,'files');self.assertEqual(state.view.query,'6q?-live');self.assertTrue(state.search)
        generation=state.files_generation
        tui._accept_result(state,'files',generation-1,files.result('complete',[{'name':'stale'}],query='old'))
        self.assertEqual(state.results['files'].context['state'],'searching');self.assertIn('files',state.busy)
        tui._accept_result(state,'files',generation,files.result('empty',query=state.view.query));self.assertNotIn('files',state.busy)
        tui._handle(state,'\x1b',lambda *a:None,None);self.assertEqual(state.view.query,'')

    def test_four_copy_scopes_tsv_unicode_and_whole_search_are_not_viewport_limited(self):
        state=tui.State();state.section=2;state.results['files']=files.result('complete',[{'name':'doc ü','path':'/tmp/a\nfile.txt','kind':'documents'},{'name':'Folder','path':'/tmp/folder','kind':'folders'}],query='example')
        state.view.group='documents';state.detail=dict(state.rows()[0])
        self.assertEqual([key for key,_ in tui._copy_options(state)],['selected','path','current','all'])
        text=copy_report(state.results['files'],'current',current=state.rows(),selected=state.detail,format='names');self.assertEqual(text,'doc ü')
        text=copy_report(state.results['files'],'all',current=state.rows(),selected=state.detail,format='names');self.assertIn('Folder',text)
        text=copy_report(state.results['files'],'selected',current=[],selected=state.detail,format='tsv')
        rows=list(csv.reader(io.StringIO(text),delimiter='\t'));self.assertEqual(rows[1][2],'/tmp/a\nfile.txt')
        self.assertNotIn('version',dict(sort_options('files')))

    def test_clipboard_preserves_tsv_tabs_without_escape_codes(self):
        with patch.object(tui,'find_executable',return_value='/pbcopy'),patch.object(tui.subprocess,'run') as run:
            tui._copy('name\tpath\nü\t/tmp')
        self.assertEqual(run.call_args.kwargs['input'],'name\tpath\nü\t/tmp')

    def test_render_uses_cached_actions_and_filtered_rows_without_bundle_io(self):
        state=tui.State();state.results['apps']=Result('apps','ok',[{'name':'Editor','path':'/test.app','version':'1','_actions':{'open':('app','/test.app'),'paths':[('Path','/test.app')]}}])
        with patch.object(actions,'target',side_effect=AssertionError('render must not validate')),patch.object(actions,'existing_path',side_effect=AssertionError('render must not stat')):
            for _ in range(10):build_frame(state,120,30)
        self.assertEqual(len(state._row_cache),1)

    def test_arrows_switch_sections_from_help_and_invisible_intro_does_not_block_small_window_quit(self):
        state=tui.State();tui._handle(state,'?',lambda *a:None,None)
        tui._handle(state,tui.curses.KEY_RIGHT,lambda *a:None,None)
        self.assertEqual(state.key,'brew');self.assertEqual(state.overlay,'')
        state=tui.State();state.intro_static=True;build_frame(state,40,10)
        self.assertFalse(tui._handle(state,'q',lambda *a:None,None))

    def test_removed_settings_and_language_environment_do_not_affect_interface(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'settings.json';path.write_text('{personal old config}')
            with patch.dict(os.environ,{'PEEK_CONFIG':str(path),'PEEK_LANG':'ru','LANG':'pl_PL.UTF-8'}):
                state=tui.State();tui._handle(state,',',lambda *a:None,None)
                self.assertEqual(state.overlay,'');self.assertEqual(state.t('apps'),'Applications')
            self.assertEqual(path.read_text(),'{personal old config}')

    def test_files_reports_distinguish_not_searched_and_in_progress(self):
        from peekcli.output import human
        for state,label in [('idle','Not searched yet'),('searching','Searching filenames'),('limited','Partial search'),('cancelled','Search cancelled')]:
            report=human(files.result(state),verbose=True)
            self.assertIn(label,report);self.assertNotIn('Scan complete',report)
            if state in {'idle','searching'}:self.assertNotIn('No entries found',report)

    def test_files_refresh_restores_path_after_sort_changes_and_when_section_is_inactive(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'needle-b.txt').touch();selected=root/'needle-c.txt';selected.touch()
            state=tui.State();state.section=2;state.files_scope=str(root);state.view.query='needle'
            state.results['files']=files.search('needle',scope=str(root));state.view.selected=1
            self.assertEqual(state.selected_row()['path'],str(selected))
            tui._handle(state,'r',lambda *a:self.fail('Files refresh uses its existing worker'),None)
            generation=state.files_generation
            build_frame(state,120,30)  # Empty loading frame clamps the numeric selection.
            self.assertEqual(state.view.selected,0)
            tui._accept_result(state,'files',generation-1,files.search('needle',scope=str(root)))
            self.assertIsNotNone(state.files_selection)
            (root/'needle-a.txt').touch();fresh=files.search('needle',scope=str(root))
            tui._handle(state,'1',lambda *a:None,None)
            tui._accept_result(state,'files',generation,fresh)
            tui._handle(state,'3',lambda *a:None,None)
            self.assertEqual(state.selected_row()['path'],str(selected));self.assertEqual(state.view.selected,2)
            self.assertIsNone(state.files_selection)

    def test_files_refresh_deleted_selection_falls_back_and_does_not_leak_into_new_search(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for name in ('needle-a','needle-b','needle-c'):(root/name).touch()
            state=tui.State();state.section=2;state.files_scope=str(root);state.view.query='needle'
            state.results['files']=files.search('needle',scope=str(root));state.view.selected=2
            tui._handle(state,'r',lambda *a:None,None);(root/'needle-c').unlink()
            build_frame(state,120,30)
            tui._accept_result(state,'files',state.files_generation,files.search('needle',scope=str(root)))
            self.assertEqual(state.selected_row()['path'],str(root/'needle-b'));self.assertEqual(state.view.selected,1)
            tui._handle(state,'r',lambda *a:None,None)
            for path in root.iterdir():path.unlink()
            tui._accept_result(state,'files',state.files_generation,files.search('needle',scope=str(root)))
            self.assertIsNone(state.selected_row());self.assertEqual(state.view.selected,0)
            (root/'needle-new').touch();state.results['files']=files.search('needle',scope=str(root))
            tui._handle(state,'r',lambda *a:None,None);state.view.query='different';tui._files_changed(state)
            self.assertIsNone(state.files_selection)
            state.view.query='needle';state.results['files']=files.search('needle',scope=str(root))
            state.files_scope=str(root/'elsewhere');tui._files_changed(state,refresh=True)
            self.assertIsNone(state.files_selection)

    def test_files_filter_choice_requests_new_matches_without_invalidating_snapshot(self):
        state=tui.State();state.section=2;state.view.query='needle';state.results['files']=files.result('complete',query='needle')
        tui._open(state,'filter',[('documents','Documents')]);generation=state.files_generation
        tui._handle(state,'\n',lambda *a:self.fail('must not start another collector'),None)
        self.assertEqual(state.view.group,'documents');self.assertEqual(state.files_generation,generation+1)
        self.assertFalse(state.files_refresh);self.assertEqual(state.overlay,'')
