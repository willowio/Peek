import unittest
from unittest.mock import patch
from peekcli import tui
from peekcli.models import Result
from peekcli.views import copy_report
from peekcli.screens import build_frame, context_keys


class CopyFormatTests(unittest.TestCase):
    def state(self, section, data):
        state=tui.State()
        state.section=next(i for i,(_,key) in enumerate(tui.MENU) if key==section)
        state.results[section]=Result(section,'ok',data)
        return state

    def test_app_scope_filter_selected_and_no_viewport_limit(self):
        rows=[{'name':f'App {i:03}','version':'1.2','path':'/private/path'} for i in range(100)]
        result=Result('apps','ok',rows)
        names=copy_report(result,'all',current=rows[:2],selected=rows[0],format='names')
        self.assertEqual(names,'\n'.join(row['name'] for row in rows))
        self.assertEqual(copy_report(result,'current',current=rows[:2],selected=None,format='summary'),'App 000  1.2\nApp 001  1.2')
        self.assertEqual(copy_report(result,'selected',current=rows,selected=rows[9],format='names'),'App 009')
        self.assertIn('Path:',copy_report(result,'selected',current=rows,selected=rows[0]))

    def test_brew_groups_versions_and_taps(self):
        result=Result('brew','ok',{'formulae':[{'name':'git','version':'2'}],'casks':[{'name':'editor','version':'3'}],'taps':[{'name':'owner/tap','path':'/private/tap'}]})
        self.assertEqual(copy_report(result,'formula',current=[],selected=None,format='summary'),'git  2')
        self.assertEqual(copy_report(result,'cask',current=[],selected=None,format='names'),'editor')
        self.assertEqual(copy_report(result,'tap',current=[],selected=None,format='summary'),'owner/tap')

    def test_shortcuts_all_sections_and_status_variants(self):
        cases=[('apps',[{'name':'Editor','version':'3'}],'Editor  3'),
               ('brew',{'formulae':[{'name':'git','version':'2'}]},'git  2'),
               ('security',[{'name':'Firewall','state':'Disabled'}],'Firewall  Disabled'),
               ('services',{'launch_items':[{'label':'job','loaded':True}]},'job  Loaded'),
               ('dev',[{'name':'git','state':'Available'}],'git  Available')]
        for section,data,expected in cases:
            for key in ('n','v'):
                with self.subTest(section=section,key=key):
                    state=self.state(section,data)
                    tui._handle(state,'c',lambda *a:None,None)
                    with patch.object(tui,'_copy',return_value='Copied') as clipboard:
                        tui._handle(state,key,lambda *a:None,None)
                    self.assertEqual(clipboard.call_args.args[0],expected.split('  ')[0] if key=='n' else expected)
                    self.assertEqual(state.overlay,'')

    def test_filter_scope_shortcuts_search_and_path(self):
        state=self.state('apps',[{'name':'One','version':'1','path':'/one'},{'name':'Two','version':'2'}])
        state.view.query='Two';tui._handle(state,'c',lambda *a:None,None)
        state.option=next(i for i,(key,_) in enumerate(state.options) if key=='current')
        with patch.object(tui,'_copy',return_value='Copied') as clipboard:tui._handle(state,'n',lambda *a:None,None)
        clipboard.assert_called_once_with('Two')
        state.view.query='';tui._handle(state,'c',lambda *a:None,None)
        state.option=next(i for i,(key,_) in enumerate(state.options) if key=='path')
        self.assertNotIn('n',dict(context_keys(state,'copy')))
        with patch.object(tui,'_copy') as clipboard:tui._handle(state,'n',lambda *a:None,None)
        clipboard.assert_not_called()
        tui._handle(state,'\x1b',lambda *a:None,None)
        tui._handle(state,'/',lambda *a:None,None)
        tui._handle(state,'n',lambda *a:None,None);tui._handle(state,'v',lambda *a:None,None)
        self.assertEqual(state.view.query,'nv')

    def test_copy_help_and_back_keys(self):
        state=self.state('apps',[{'name':'Editor','version':'1'}]);tui._handle(state,'c',lambda *a:None,None)
        text=' '.join(span.text for span in build_frame(state,120,30).spans)
        self.assertIn('n Names',text);self.assertIn('v Names + versions',text)
        tui._handle(state,'?',lambda *a:None,None);self.assertEqual(state.overlay,'help')
        tui._handle(state,'\x1b',lambda *a:None,None);self.assertEqual(state.overlay,'copy')
