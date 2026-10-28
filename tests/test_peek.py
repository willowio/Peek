from __future__ import annotations
import io
import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from peekcli import tui
from peekcli.cli import main
from peekcli.models import Result
from peekcli.output import human
from peekcli.system import Command, run
from peekcli.collectors import apps, brew, security, services
from peekcli.views import copy_report, select, copy_scopes
from peekcli.text import safe, clip, cell_width


def app_result(n=50):
    return Result('apps', 'ok', [dict(name=f'App {i:03}', path=f'/Applications/App {i:03}.app', version='1.0',
                  ownership='apple' if i%2 else 'non_apple', source={'category':'apple' if i%2 else 'third_party','basis':'fixture','confidence':'fixture'}, bundle_id=f'com.test.{i}') for i in range(n)])


class BundleTests(unittest.TestCase):
    def test_invalid_candidates_unknown_identity_and_terminal_escapes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for d in ['One.app','Two.app','escape\x1b[2J.app']:
                (root/d).mkdir()
            with patch.object(apps.platform,'system',return_value='Darwin'):
                r=apps.collect(roots=[root])
            self.assertEqual(len(r.data),3)
            self.assertEqual(r.status,'partial')
            self.assertTrue(all(x['ownership']=='unknown' for x in r.data))
            self.assertNotIn('\x1b',human(r))

    def test_tree_never_follows_loops_or_outside_symlinks_and_limits_entries(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'A.app'; root.mkdir()
            (root/'loop').symlink_to(root, target_is_directory=True)
            (root/'outside').symlink_to('/etc',target_is_directory=True)
            for i in range(20): (root/f'file{i}').write_text('ok')
            tree=apps.bundle_tree(root, depth=5, limit=8)
            self.assertLessEqual(len(tree['entries']),8)
            self.assertTrue(tree['truncated'])
            tree=apps.bundle_tree(root, depth=5, limit=100)
            self.assertEqual([r['type'] for r in tree['entries'] if r['path']=='loop'],['symlink'])
            self.assertFalse(any(r['path'].startswith('outside/') for r in tree['entries']))

    def test_inspect_arbitrary_bundle_tree_escape_size_and_no_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'Test.app'; (root/'Contents/MacOS').mkdir(parents=True)
            (root/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'com.apple.imposter','CFBundleVersion':'42'}))
            (root/'Contents/MacOS/not-a-command').write_text('not executed')
            with patch.object(apps,'run') as command:
                r=apps.inspect_bundle(str(root),tree=True,size=True)
            command.assert_not_called()
            self.assertEqual(r.status,'ok')
            self.assertIn('unverified',r.data['origin_evidence'])
            self.assertTrue(r.data['size']['complete'])
            r=apps.inspect_bundle(str(root),tree=True,subdir='../')
            self.assertEqual(r.status,'partial')
            self.assertIn('inside',r.errors[0])

    def test_malformed_xml_and_non_dictionary_service_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'a.plist'; p.write_text('<?xml version=oops?>')
            self.assertIsNone(services.parse_plist(p,'Agent'))
            p.write_bytes(plistlib.dumps(['not a dictionary']))
            self.assertIsNone(services.parse_plist(p,'Agent'))

    def test_copy_versions_do_not_disappear(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for name, version in [('A','1'),('B','2')]:
                p=root/name/'Same.app/Contents'; p.mkdir(parents=True)
                (p/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'org.test.same','CFBundleVersion':version}))
            with patch.object(apps.platform,'system',return_value='Darwin'):
                r=apps.collect(roots=[root])
            self.assertEqual(len(r.data),1)
            self.assertEqual({x['version'] for x in r.data[0]['copies']},{'1','2'})


class EvidenceTests(unittest.TestCase):
    def test_failed_security_command_never_claims_enabled(self):
        with patch.object(security,'find_executable',return_value='/cmd'), patch.object(security,'run',return_value=Command(stdout='enabled',returncode=1)):
            row=security.check('SIP',['csrutil','status'],('enabled',),('disabled',))
        self.assertEqual(row['state'],'Error')
        self.assertIn('enabled',row['evidence'])
        self.assertIn('source',row)
        self.assertIn('limitation',row)

    def test_security_has_six_controls_and_unrecognized_output_is_partial(self):
        with patch.object(security.platform,'system',return_value='Darwin'), patch.object(security,'find_executable',return_value='/cmd'), patch.object(security,'run',return_value=Command(stdout='new output')):
            r=security.collect()
        self.assertEqual(len(r.data),6)
        self.assertEqual(r.status,'partial')
        self.assertTrue(all(x['state']=='Unknown' for x in r.data))

    def test_launchctl_parser_loaded_is_separate_from_running(self):
        rows=services.parse_list('PID\tStatus\tLabel\n-\t0\torg.waiting\n123\t0\torg.running\n')
        self.assertTrue(rows['org.waiting']['loaded'])
        self.assertFalse(rows['org.waiting']['running'])
        self.assertTrue(rows['org.running']['running'])
        with self.assertRaises(ValueError): services.parse_list('changed format')

    def test_configured_daemons_not_matched_to_user_domain(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'job.plist'; p.write_bytes(plistlib.dumps({'Label':'org.test'}))
            with patch.object(services.platform,'system',return_value='Darwin'), patch.object(services,'run',return_value=Command(stdout='PID Status Label\n123 0 org.test\n')):
                r=services.collect(roots=[(Path(temp),'System Launch Daemon')])
            self.assertIsNone(r.data['launch_items'][0]['loaded'])
            self.assertIsNone(r.data['launch_items'][0]['running'])

    def test_brew_reads_receipts_and_never_info_or_tap_info(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            keg=root/'Cellar/git/1.0'; keg.mkdir(parents=True)
            (keg/'INSTALL_RECEIPT.json').write_text(json.dumps({'installed_on_request':False,'source':{'tap':'homebrew/core'}}))
            cask=root/'Caskroom/editor'; (cask/'2.0').mkdir(parents=True); (cask/'.metadata').mkdir()
            (cask/'.metadata/INSTALL_RECEIPT.json').write_text(json.dumps({'source':{'tap':'homebrew/cask'}}))
            (root/'Library/Taps/owner/homebrew-tools').mkdir(parents=True)
            flags={'--prefix':root,'--cellar':root/'Cellar','--caskroom':root/'Caskroom','--repository':root}
            calls=[]
            def command(args,**kwargs):
                calls.append((args,kwargs)); return Command(stdout=str(flags[args[1]])+'\n')
            with patch.object(brew,'find_executable',return_value='/brew'), patch.object(brew,'run',side_effect=command):
                r=brew.collect()
            self.assertEqual(r.status,'ok')
            self.assertFalse(r.data['formulae'][0]['requested'])
            self.assertEqual(r.data['taps'][0]['name'],'owner/tools')
            self.assertEqual(len(calls),4)
            self.assertTrue(all(c[1]['env']['HOMEBREW_NO_AUTO_UPDATE']=='1' for c in calls))
            self.assertEqual({c[0][1] for c in calls},set(flags))

    def test_broken_brew_paths_are_error_not_empty_success(self):
        with patch.object(brew,'find_executable',return_value='/brew'), patch.object(brew,'run',return_value=Command(returncode=1,stderr='broken')):
            r=brew.collect()
        self.assertEqual(r.status,'error')
        self.assertEqual(len(r.errors),4)

    def test_subprocess_arguments_locale_and_timeouts(self):
        with patch('peekcli.system.subprocess.run',return_value=subprocess.CompletedProcess([],0,'','')) as proc:
            run(['/utility','path;touch /tmp/bad'],timeout=3)
        self.assertEqual(proc.call_args.args[0],['/utility','path;touch /tmp/bad'])
        self.assertEqual(proc.call_args.kwargs['env']['LC_ALL'],'C')
        self.assertEqual(proc.call_args.kwargs['timeout'],3)


class ReportsAndCliTests(unittest.TestCase):
    def invoke(self,args):
        output,errors=io.StringIO(),io.StringIO()
        with patch('sys.stdout',output),patch('sys.stderr',errors): code=main(args)
        return code,output.getvalue(),errors.getvalue()


    def test_brew_taps_have_separate_count_and_copy(self):
        result=Result('brew','ok',{'formulae':[{'name':'git','requested':True}], 'casks':[], 'taps':[{'name':'owner/tap','path':'/tap'}]})
        text=copy_report(result,'all',current=[],selected=None)
        self.assertIn('Taps (1)',text)
        self.assertIn('owner/tap',text)
        self.assertIn('owner/tap',copy_report(result,'tap',current=[],selected=None))
        self.assertNotIn('git',copy_report(result,'tap',current=[],selected=None))

    def test_full_copy_is_not_limited_to_viewport(self):
        result=app_result(100)
        text=copy_report(result,'all',current=result.data[:2],selected=result.data[0])
        self.assertIn('App 099',text)
        filtered=copy_report(result,'current',current=result.data[:2],selected=None)
        self.assertNotIn('App 099',filtered)
        self.assertIn('Scope: Visible Results',filtered)
        self.assertIn('Selected Item',dict(copy_scopes(result)).values())

    def test_search_matches_identifiers_and_unknown_scope(self):
        result=app_result(10)
        self.assertEqual(len(select(result,query='com.test.3')),1)
        self.assertEqual(len(select(result,group='unknown')),0)



    def test_clipboard_failure_preserves_actionable_error(self):
        with patch.object(tui,'find_executable',return_value='/pbcopy'),patch.object(tui.subprocess,'run',side_effect=subprocess.TimeoutExpired('pbcopy',3)):
            text=tui._copy('report')
        self.assertIn('Clipboard failed',text)
        self.assertIn('displayed information',text)


class Screen:
    def __init__(self,h=24,w=80): self.h,self.w=h,w; self.calls=[]
    def getmaxyx(self): return self.h,self.w
    def erase(self): self.calls=[]
    def addstr(self,y,x,text,attr=0):
        if x+cell_width(text)>self.w-1 or y>=self.h: raise AssertionError((y,x,text,self.w,self.h))
        self.calls.append((y,x,text,attr))
    def refresh(self): pass


class InterfaceTests(unittest.TestCase):
    def state(self):
        state=tui.State(); state.results['apps']=app_result(100); return state

    def test_six_sections_and_number_navigation_collects_lazily(self):
        state=self.state(); tasks=[]
        self.assertEqual(len(tui.MENU),6)
        tui._handle(state,'4',lambda *x:tasks.append(x),None)
        self.assertEqual(state.key,'security')
        self.assertEqual(tasks[0][0],'security')

    def test_layout_sizes_unicode_long_paths_resize_and_selection_bounds(self):
        state=self.state(); state.results['apps'].data[0]['name']='界e\u0301'+('long'*50)
        state.results['apps'].data[0]['path']='/'+('long/'*100)+'\x1b[2J'
        for w,h in [(60,15),(79,20),(80,24),(119,30),(120,24),(160,40),(220,60),(39,10)]:
            state.view.selected=99
            screen=Screen(h,w)
            with patch.object(tui,'_attr',return_value=0): tui._draw(screen,state)
            text='\n'.join(x[2] for x in screen.calls)
            self.assertNotIn('\x1b',text)
            if w>=60:
                self.assertIn('App 099',text)
                self.assertIn('? Help',text)
                self.assertGreater(state.view.scroll,0)
            else: self.assertIn('60 columns',text)

    def test_search_filter_sort_copy_menus_and_modal_q(self):
        state=self.state()
        noop=lambda *args:None
        tui._handle(state,'/',noop,None)
        for c in 'App 099': tui._handle(state,c,noop,None)
        self.assertEqual(len(state.rows()),1)
        tui._handle(state,'\n',noop,None)
        tui._handle(state,'c',noop,None)
        self.assertEqual(state.overlay,'copy')
        self.assertTrue(tui._handle(state,'q',noop,None))
        self.assertEqual(state.overlay,'')
        self.assertFalse(tui._handle(state,'q',noop,None))
        tui._handle(state,'f',noop,None)
        state.option=1
        tui._handle(state,'\n',noop,None)
        self.assertEqual(state.view.group,'apple')

    def test_refresh_failure_keeps_data_filter_selection_and_section(self):
        state=self.state(); old=state.results['apps']; state.view.selected=40; state.view.group='apple'
        tui._accept_result(state,'apps',0,Result('apps','error',[],errors=['denied']))
        self.assertIs(state.results['apps'],old)
        self.assertEqual(state.view.selected,40)
        self.assertEqual(state.view.group,'apple')
        self.assertIn('retained',state.message)

    def test_stale_detail_result_is_ignored(self):
        state=self.state(); state.detail={'name':'Current'}; state.detail_token=2
        tui._accept_result(state,'detail',1,Result('app','ok',{'name':'Stale'}))
        self.assertEqual(state.detail['name'],'Current')

    def test_no_color_selection_is_visible(self):
        with patch.dict(os.environ,{'NO_COLOR':'1'}):
            self.assertTrue(tui._attr(selected=True)&tui.curses.A_REVERSE)

    def test_terminal_text_sanitizing_and_wide_clipping(self):
        self.assertNotIn('\x1b',safe('bad\x1b]52;stuff\x07'))
        self.assertLessEqual(cell_width(clip('世界hello',5)),5)
        self.assertEqual(clip('text',0),'')




if __name__=='__main__': unittest.main()
