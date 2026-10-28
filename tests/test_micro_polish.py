from pathlib import Path
from types import SimpleNamespace
import json
import os
import stat
import tempfile
import unittest
from unittest.mock import patch
from peekcli import tui
from peekcli.collectors import apps
from peekcli.layout import Layout
from peekcli.models import Result
from peekcli.screens import build_frame,footer
from peekcli.text import cell_width


class MicroPolishTests(unittest.TestCase):
    def test_protected_cryptex_application_source_resolves_links_without_name_special_case(self):
        root=Path('/System/Volumes/Preboot/Cryptexes/App/System/Applications')
        for location,uid,flags,identifier,expected in [
            (root/'Any.app',0,getattr(stat,'SF_RESTRICTED',0x80000),'com.apple.any','apple'),
            (root/'Any.app',501,getattr(stat,'SF_RESTRICTED',0x80000),'com.apple.any','unknown'),
            (root/'Any.app',0,0,'com.apple.any','unknown'),
            (root/'Any.app',0,getattr(stat,'SF_RESTRICTED',0x80000),'org.example.any','unknown'),
            (root.parent/'Other/Any.app',0,getattr(stat,'SF_RESTRICTED',0x80000),'com.apple.any','unknown')]:
            with patch.object(Path,'resolve',return_value=location),patch.object(Path,'stat',return_value=SimpleNamespace(st_uid=uid,st_flags=flags)),patch.object(apps,'run') as command:
                result=apps.source_info(Path('/Applications/Any.app'),{'bundle_id':identifier})
            self.assertEqual(result['category'],expected);command.assert_not_called()


    def test_selection_fills_list_width_and_rule_is_absent_after_navigation_and_resize(self):
        state=tui.State();state.results['apps']=Result('apps','ok',[{'name':f'App {i}','version':'1','source':{'category':'third_party'}} for i in range(80)])
        for width,height in [(60,15),(80,24),(100,28),(120,30),(160,40),(60,15)]:
            for index in [0,15,79,1]:
                state.view.selected=index
                frame=build_frame(state,width,height);layout=Layout.measure(width,height)
                rect=layout.panes()[0] if layout.wide else layout.body
                active=[span for span in frame.spans if span.selected and span.y>=rect.y]
                self.assertEqual(len(active),1);self.assertEqual(active[0].x,rect.x);self.assertEqual(cell_width(active[0].text),rect.width)
                self.assertFalse(any(span.text.startswith('---') for span in frame.spans))
                dividers=[span for span in frame.spans if span.text=='│']
                self.assertEqual(len(dividers),layout.body.height if layout.wide else 0)
                if dividers:self.assertEqual({span.x for span in dividers},{layout.panes()[1].x})

    def test_selected_controls_share_filled_style_with_monochrome_fallback(self):
        with patch.dict(os.environ,{},clear=True),patch.object(tui,'_MONO',False),patch.object(tui,'_FILLED_SELECTION',True),patch.object(tui.curses,'COLOR_PAIRS',256,create=True),patch.object(tui.curses,'color_pair',return_value=0) as color:
            attr=tui._attr('logo',True)
            color.assert_called_once_with(tui.PAIRS['selection']);self.assertFalse(attr&tui.curses.A_UNDERLINE)
        with patch.object(tui,'_MONO',True):
            attr=tui._attr('logo',True)
            self.assertTrue(attr&tui.curses.A_REVERSE);self.assertFalse(attr&tui.curses.A_UNDERLINE)
        with patch.object(tui,'_MONO',False),patch.object(tui,'_FILLED_SELECTION',False):
            self.assertTrue(tui._attr('logo',True)&tui.curses.A_REVERSE)
        state=tui.State()
        for overlay in ['','help','copy','filter']:
            state.overlay=overlay;state.options=[('all','All')]
            frame=build_frame(state,160,40)
            self.assertTrue(any(s.selected and '1 Applications' in s.text for s in frame.spans))
            if overlay=='help':self.assertTrue(any('Help · Controls' in s.text for s in frame.spans))
            if overlay in {'filter','copy'}:
                content=[s for s in frame.spans if s.selected and s.text.startswith('> ')]
                self.assertEqual(len(content),1);self.assertLessEqual(cell_width(content[0].text),64)

    def test_footer_matches_detail_type_and_document_controls(self):
        state=tui.State();state.detail={'name':'Example','path':'/Applications/Example.app'}
        with patch('peekcli.screens.platform.system',return_value='Darwin'):
            text=footer(state,156)
        for token in ['Esc Back','y Copy','? Help']:self.assertIn(token,text)
        state.section=2;state.detail={'name':'SIP'}
        text=footer(state,156)
        for token in ['b Bundle','v Verify','f Finder']:self.assertNotIn(token,text)
        for overlay in ['diagnostics','evidence']:
            state.overlay=overlay;text=footer(state,156)
            self.assertIn('Esc Back',text);self.assertNotIn('Enter',text)
        for width in [56,76,96,116,156]:self.assertLessEqual(cell_width(footer(state,width)),width)


if __name__=='__main__':unittest.main()
