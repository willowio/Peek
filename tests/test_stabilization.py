from pathlib import Path
import json
import os
import plistlib
import stat
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from peekcli import branding,settings,tui
from peekcli.animation import Timeline
from peekcli.collectors import apps
from peekcli.i18n import LANGUAGES,catalog
from peekcli.keymap import HELP_TOPICS
from peekcli.layout import Layout
from peekcli.models import Result
from peekcli.screens import build_frame,detail_lines,settings_options
from peekcli.text import cell_width
from peekcli.views import select


class StabilizedSourceTests(unittest.TestCase):
    def bundle(self,root,identifier='org.example.app',copyright=None):
        path=root/'Example.app';(path/'Contents/MacOS').mkdir(parents=True)
        metadata={'CFBundleIdentifier':identifier,'CFBundleName':'Example','CFBundlePackageType':'APPL','CFBundleExecutable':'example'}
        if copyright:metadata['NSHumanReadableCopyright']=copyright
        (path/'Contents/Info.plist').write_bytes(plistlib.dumps(metadata))
        (path/'Contents/MacOS/example').write_text('never executed')
        return path

    def test_third_party_source_does_not_require_or_assert_signature_verification(self):
        with tempfile.TemporaryDirectory() as temp:
            path=self.bundle(Path(temp))
            with patch.object(apps,'run') as run:row=apps.parse_app(path)
            run.assert_not_called()
            self.assertEqual(apps.source_of(row),'third_party')
            self.assertEqual(row['verification_state'],'not_checked')
            self.assertIn('not authenticated',row['source']['basis'])

    def test_protected_apple_source_needs_system_location_root_owner_and_restricted_flag(self):
        p=Path('/System/Applications/Example.app')
        metadata={'bundle_id':'com.apple.example'}
        for uid,flags,expected in [(0,getattr(stat,'SF_RESTRICTED',0x80000),'apple'),(501,getattr(stat,'SF_RESTRICTED',0x80000),'unknown'),(0,0,'unknown')]:
            with patch.object(Path,'resolve',return_value=p),patch.object(Path,'stat',return_value=SimpleNamespace(st_uid=uid,st_flags=flags)):
                source=apps.source_info(p,metadata)
            self.assertEqual(source['category'],expected)
        with patch.object(Path,'resolve',return_value=Path('/Applications/Example.app')),patch.object(Path,'stat',return_value=SimpleNamespace(st_uid=0,st_flags=getattr(stat,'SF_RESTRICTED',0x80000))):
            self.assertEqual(apps.source_info(Path('/Applications/Example.app'),metadata)['category'],'unknown')

    def test_modified_or_unsigned_bundle_keeps_source_separate_from_failed_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            path=self.bundle(Path(temp));row=apps.parse_app(path)
            row['verification_state']='failed';row['signing']={'validation':'Unverified or invalid'}
            self.assertEqual(apps.source_info(path,row)['category'],'third_party')
            text='\n'.join(line for line,_ in detail_lines(row,'apps',lambda key:key))
            self.assertIn('verification_failed',text)
            self.assertIn('third_party',text)

    def test_failed_validation_of_modified_bundle_does_not_erase_declared_source(self):
        from peekcli.system import Command
        def command(args,**kwargs):
            if args[0].endswith('lipo'):return Command(stdout='arm64')
            if '--verify' in args:return Command(returncode=1,stderr='modified resource')
            return Command(stderr='Authority=Example')
        with tempfile.TemporaryDirectory() as temp:
            path=self.bundle(Path(temp))
            with patch.object(apps.platform,'system',return_value='Darwin'),patch.object(apps,'run',side_effect=command):
                result=apps.inspect_bundle(str(path),signing=True)
            self.assertEqual(result.data['verification_state'],'failed')
            self.assertEqual(apps.source_of(result.data),'third_party')
            self.assertIn('modified resource',result.data['signing']['evidence'])

    def test_metadata_only_apple_claim_outside_system_is_unknown(self):
        with tempfile.TemporaryDirectory() as temp:
            path=self.bundle(Path(temp),'com.apple.fake')
            self.assertEqual(apps.source_of(apps.parse_app(path)),'unknown')

    def test_filters_partition_source_records_without_signature_coupling(self):
        records=[{'name':str(i),'source':{'category':category},'verification_state':'not_checked'} for i,category in enumerate(['apple','third_party','unknown','apple'])]
        result=Result('apps','ok',records)
        self.assertEqual(sum(len(select(result,group=x)) for x in ['apple','third_party','unknown']),len(records))
        self.assertEqual(len(select(result,group='apple')),2)


class StabilizedGeometryTests(unittest.TestCase):
    def test_canonical_logo_retains_approved_bytes(self):
        packaged=Path(__file__).parents[1]/'src/peekcli/wordmark.txt'
        self.assertEqual(__import__('hashlib').sha256(packaged.read_bytes()).hexdigest(),'bef26971d09015af90eb1453dc267e6124c0427aac3e2a073e5c1190f4f12ece')
        self.assertEqual(tuple(branding.WORDMARK.splitlines()),branding.COMPACT_WORDMARK)

    def test_intro_centers_whole_canonical_composition_at_every_supported_width(self):
        class Phase:
            kind='intro'
            def progress(self):return .65
            def active(self):return True
        for width,height in [(60,15),(80,24),(100,28),(120,30),(160,40)]:
            state=tui.State();state.effect=Phase();frame=build_frame(state,width,height)
            phrase=next(span for span in frame.spans if span.text==branding.TAGLINE)
            self.assertLessEqual(abs((phrase.x+cell_width(phrase.text)/2)-width/2),.5)
            art=branding.WORDMARK.splitlines();expected_y=(height-len(art)-2)//2
            self.assertEqual(frame.spans[0].y,expected_y)
            self.assertEqual(frame.spans[0].x,(width-max(map(cell_width,art)))//2)

    def test_header_uses_the_same_artwork_and_compact_fallback_is_plain_peek(self):
        state=tui.State()
        frame=build_frame(state,120,30)
        for i,line in enumerate(branding.WORDMARK.splitlines()):self.assertTrue(any(span.y==i and span.text==line for span in frame.spans))
        short=build_frame(state,60,15);self.assertTrue(any(s.text=='Peek' for s in short.spans))
        self.assertFalse(any(branding.TAGLINE in s.text for s in frame.spans))

    def test_all_screens_are_bounded_and_dialogs_are_borderless(self):
        for language in ['en','de','pt_BR']:
            for width,height in [(60,15),(80,18),(80,24),(100,28),(120,30),(160,40)]:
                state=tui.State(preferences=settings.Preferences(language=language));state.results['apps']=Result('apps','ok',[{'name':'世界e\u0301'*100,'path':'/'+'long/'*100,'version':'1.0','source':{'category':'unknown'}}])
                for overlay in ['','settings','help','filter','sort','copy','setting:language','diagnostics','evidence','about']:
                    state.overlay=overlay;state.options=[('all','All')]
                    frame=build_frame(state,width,height)
                    for span in frame.spans:self.assertTrue(0<=span.y<height and 0<=span.x and span.x+cell_width(span.text)<width)
                    borders=[s for s in frame.spans if s.text.startswith('+') and s.text.endswith('+')]
                    self.assertFalse(borders)
                    if overlay:self.assertFalse(any(s.text in {'|','│'} for s in frame.spans))

    def test_settings_and_sparse_details_have_bounded_content_width(self):
        state=tui.State();state.overlay='settings'
        frame=build_frame(state,160,40)
        panel=[s for s in frame.spans if s.y>8 and s.role!='cyan' and s.y<38]
        self.assertLessEqual(max(cell_width(s.text) for s in panel),68)
        self.assertLess(max(s.y for s in panel)-min(s.y for s in panel),20)
        state.overlay='';state.section=1;state.detail={'name':'example','kind':'formula','version':'1','dependencies':[],'dependencies_collected':True,'requested':False,'dependency':True}
        state.results['brew']=Result('brew','ok',{'formulae':[state.detail],'casks':[],'taps':[]})
        wide=build_frame(state,160,40)
        self.assertFalse(any(s.text.startswith('+') for s in wide.spans))
        self.assertTrue(any(s.text=='│' for s in wide.spans))
        text='\n'.join(line for line,_ in detail_lines(state.detail,'brew',state.t))
        self.assertNotIn('Dependencies',text);self.assertNotIn('None recorded',text);self.assertNotIn('Unknown',text)

    def test_only_selection_pair_sets_background_without_changing_terminal_palette(self):
        with patch.dict(os.environ,{},clear=True),patch.object(tui.curses,'has_colors',return_value=True),patch.object(tui.curses,'start_color'),patch.object(tui.curses,'use_default_colors'),patch.object(tui.curses,'COLORS',256,create=True),patch.object(tui.curses,'COLOR_PAIRS',256,create=True),patch.object(tui.curses,'init_color') as palette,patch.object(tui.curses,'init_pair') as pair:
            tui._init_colors()
        palette.assert_not_called();self.assertTrue(pair.called)
        self.assertTrue(all(call.args[2]==-1 for call in pair.call_args_list if call.args[0]!=tui.PAIRS['selection']))
        selection=next(call.args for call in pair.call_args_list if call.args[0]==tui.PAIRS['selection'])
        self.assertEqual(selection[2],146)

    def test_monochrome_still_initializes_default_background_contract(self):
        with patch.dict(os.environ,{'NO_COLOR':'1'},clear=True),patch.object(tui.curses,'has_colors',return_value=True),patch.object(tui.curses,'start_color'),patch.object(tui.curses,'use_default_colors') as defaults,patch.object(tui.curses,'init_pair') as pair:
            tui._init_colors()
        defaults.assert_called_once();pair.assert_not_called()

    def test_missing_path_is_not_offered_or_copied(self):
        state=tui.State();state.results['security']=Result('security','ok',[{'name':'SIP','state':'Enabled'}]);state.section=2
        self.assertNotIn('path',dict(tui._copy_options(state)))
        with patch.object(tui,'_copy') as copy:
            tui._handle(state,'x',lambda *args:None,None)
        copy.assert_not_called()

    def test_settings_exposes_only_two_real_preferences(self):
        state=tui.State()
        self.assertEqual([key for key,_,_ in settings_options(state)],['language','intro'])
        self.assertEqual(set(settings.CHOICES),{'language'})
        state.section=1;state.results['brew']=Result('brew','ok',{'formulae':[{'name':'example','dependency':None}],'casks':[],'taps':[]})
        from peekcli.screens import group_options
        self.assertNotIn('dependency',dict(group_options(state)));self.assertNotIn('requested',dict(group_options(state)))

    def test_help_topics_navigate_without_changing_main_selection(self):
        state=tui.State();state.overlay='help';old=state.section
        for i in range(len(HELP_TOPICS)):
            tui._handle(state,'\t',lambda *args:None,None)
            self.assertEqual(state.help_topic,(i+1)%len(HELP_TOPICS))
            self.assertEqual(state.section,old)
        tui._handle(state,'\x1b',lambda *args:None,None);self.assertEqual(state.overlay,'')


if __name__=='__main__':unittest.main()
