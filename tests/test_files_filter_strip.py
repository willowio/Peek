from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from peekcli import tui,actions
from peekcli.collectors import files
from peekcli.layout import Layout
from peekcli.screens import build_frame,filter_strip_options,group_options
from peekcli.text import cell_width
from peekcli.views import FILTERS,copy_report


class FilesFilterStripTests(unittest.TestCase):
    def state(self,group='all'):
        state=tui.State();state.section=2;state.view.group=group
        state.results['files']=files.result('complete',[
            {'name':'Folder A','path':'/fixture/a','kind':'folders'},
            {'name':'Folder B','path':'/fixture/b','kind':'folders'},
            {'name':'image.dmg','path':'/fixture/image.dmg','kind':'disk_images'}],
            _type_counts={'all':3,'folders':2,'disk_images':1})
        return state

    def strip(self,state,width=120,height=30):
        frame=build_frame(state,width,height);y=Layout.measure(width,height).filters.y
        return [span for span in frame.spans if span.y==y]

    def test_all_first_and_only_matching_or_active_categories_in_strip(self):
        state=self.state('disk_images');spans=self.strip(state)
        self.assertEqual([span.text.strip() for span in spans],['All (3)','Disk Images (1)','Folders (2)'])
        self.assertTrue(spans[1].selected);self.assertFalse(spans[0].selected)
        self.assertEqual([key for key,_ in filter_strip_options(state)],['all','disk_images','folders'])

    def test_complete_menu_keeps_zero_categories_and_scope_actions_off_strip(self):
        state=self.state();menu=group_options(state)
        self.assertEqual([key for key,_ in menu],['all','folders','disk_images','archives','documents','other_files','scope','scope_default'])
        self.assertIn(('archives','Archives (0)'),menu);self.assertIn(('documents','Documents (0)'),menu)
        text=' '.join(span.text for span in self.strip(state,200))
        for excluded in ('Archives','Documents','Other Files','Applications','custom folder','Common user folders'):self.assertNotIn(excluded,text)
        tui._handle(state,'f',lambda *a:None,None)
        self.assertEqual(state.overlay,'filter');self.assertEqual(state.options,menu)

    def test_active_zero_category_remains_visible_and_understandable(self):
        state=self.state('other_files');spans=self.strip(state)
        self.assertEqual(spans[0].text.strip(),'All (3)')
        self.assertEqual(spans[1].text.strip(),'Other Files (0)');self.assertTrue(spans[1].selected)
        text='\n'.join(span.text for span in build_frame(state,80,24).spans)
        self.assertIn('0 results',text);self.assertIn('No matching items',text)
        self.assertNotIn('Archives (0)',text)

    def test_supported_narrow_widths_preserve_all_and_active_whole_chips(self):
        for width in (60,64,72,80,100):
            for height in (15,24,30):
                state=self.state('other_files');spans=self.strip(state,width,height)
                self.assertEqual(spans[0].text.strip(),'All (3)')
                self.assertEqual(spans[1].text.strip(),'Other Files (0)')
                for span in spans:
                    self.assertLessEqual(span.x+cell_width(span.text),width-1)
                    self.assertTrue(span.text.strip().endswith(')'))
                    self.assertNotIn('scope',span.text.lower())

    def test_counts_use_full_cached_matches_without_metadata_or_rescanning(self):
        state=self.state();state.results['files'].context['_type_counts']={'all':700,'folders':690,'documents':9,'archives':1}
        with patch.object(files.os,'scandir',side_effect=AssertionError('render cannot scan')),patch.object(actions,'existing_path',side_effect=AssertionError('render cannot read metadata')):
            labels=[label for _,label in filter_strip_options(state)]
            spans=self.strip(state,160)
        self.assertEqual(labels,['All (700)','Folders (690)','Archives (1)','Documents (9)'])
        self.assertIn('Documents (9)',' '.join(span.text for span in spans))

    def test_removed_app_filter_resets_to_all_without_excluding_bundles_or_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            app=Path(temp)/'Needle.app';app.mkdir();(app/'Contents').mkdir()
            found=actions.prepare_result(files.search('Needle',scope=temp))
            state=tui.State();state.section=2;state.view.group='applications';state.view.selected=99
            state.results['files']=found;spans=self.strip(state)
            self.assertEqual(state.view.group,'all');self.assertEqual(state.view.selected,0)
            self.assertEqual([row['path'] for row in state.rows()],[str(app)])
            self.assertTrue(state.selected_row()['_actions']['paths'])
            self.assertEqual(state.selected_row()['kind'],'applications')
            self.assertNotIn('applications',dict(FILTERS['files']))
            self.assertEqual(spans[0].text.strip(),'All (1)');self.assertTrue(spans[0].selected)
            self.assertNotIn('Applications',' '.join(span.text for span in spans))
            self.assertEqual(copy_report(found,'all',current=state.rows(),selected=state.selected_row(),format='names'),'Needle.app')
            tui._handle(state,'\n',lambda *a:None,None)
            self.assertEqual(state.detail['path'],str(app));self.assertEqual(state.detail['kind'],'applications')
