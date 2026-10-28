from unittest.mock import patch
import unittest
from peekcli import tui,actions
from peekcli.security_commands import CATALOG,reference,FIREWALL
from peekcli.screens import build_frame,document,footer
from peekcli.models import Result
from peekcli.text import cell_width


class SecurityCommandsTests(unittest.TestCase):
    def detail(self,name):
        state=tui.State();state.section=3;state.detail={'name':name,'state':'Disabled'};state.detail_scroll=5;state.view.selected=2
        return state

    def test_all_six_controls_show_contextual_action_and_read_only_reference(self):
        self.assertEqual(len(CATALOG),6)
        for control in CATALOG:
            state=self.detail(control)
            self.assertIn('m Show Commands',footer(state,56))
            with patch.object(tui.subprocess,'run',side_effect=AssertionError('must not execute')),patch.object(actions,'run',side_effect=AssertionError('must not execute')):
                tui._handle(state,'m',lambda *a:self.fail('must not schedule commands'),None)
                text='\n'.join(line for line,_ in document(state))
                for label in ('Observed state: Disabled','Check status','Enable','Disable','What to do afterward','never runs these commands'):
                    self.assertIn(label,text)
                self.assertIn(reference(control)['check'],text)
                tui._handle(state,'\n',lambda *a:self.fail('must not execute'),None)
                tui._handle(state,'\x1b',lambda *a:self.fail('must not execute'),None)
            self.assertEqual(state.overlay,'');self.assertEqual(state.detail_scroll,5);self.assertEqual(state.view.selected,2)
            self.assertEqual(state.detail['name'],control)

    def test_sip_recovery_restart_and_cpu_instructions(self):
        data=reference('SIP');text=' '.join(data.values())
        for value in ('csrutil status','csrutil enable','csrutil disable','Recovery Terminal','not ordinary Terminal','Apple silicon','Intel','Command-R','Restart'):self.assertIn(value,text)
        self.assertIn('not routine',text)

    def test_filevault_authentication_follow_up_and_secret_handling(self):
        data=reference('FileVault');text=' '.join(data.values())
        for value in ('fdesetup status','sudo fdesetup enable','sudo fdesetup disable','Secure Token','volume ownership','device management','login/restart','Recovery keys','reports or logs'):self.assertIn(value,text)
        self.assertIn('when supported',text)

    def test_gatekeeper_current_and_legacy_instructions_are_explicit(self):
        for version in ('15.0','27.2',''):
            data=reference('Gatekeeper',version)
            self.assertIn('System Settings',data['enable']);self.assertEqual(data['disable'],'sudo spctl --global-disable')
            self.assertIn('only reveals',data['where']);self.assertIn('does not immediately disable',data['where']);self.assertIn('deprecated',data['after'])
        legacy=reference('Gatekeeper','14.7');self.assertEqual(legacy['enable'],'sudo spctl --global-enable');self.assertIn('14 and earlier',legacy['where'])

    def test_firewall_full_paths_admin_and_dependencies(self):
        for name,flag in [('Firewall','globalstate'),('Firewall Stealth','stealthmode'),('Firewall Block All','blockall')]:
            data=reference(name)
            self.assertEqual(data['check'],FIREWALL+' --get'+flag)
            self.assertEqual(data['enable'],'sudo '+FIREWALL+' --set'+flag+' on')
            self.assertEqual(data['disable'],'sudo '+FIREWALL+' --set'+flag+' off')
            self.assertIn('No routine restart',data['after']) if name=='Firewall' else self.assertIn('no routine restart',data['after'])
            if name!='Firewall':self.assertIn('only while',data['after'])
        self.assertIn('disrupt',reference('Firewall Block All')['warning'])

    def test_reference_unavailable_outside_security_or_without_details(self):
        for index in (0,1,2,4,5):
            state=tui.State();state.section=index;state.detail={'name':'SIP','state':'Enabled'}
            tui._handle(state,'m',lambda *a:self.fail('scheduled command'),None)
            self.assertEqual(state.overlay,'');self.assertNotIn('Show Commands',footer(state,150))
        state=tui.State();state.section=3;tui._handle(state,'m',lambda *a:None,None);self.assertEqual(state.overlay,'')
        self.assertIsNone(reference('untrusted command text'))

    def test_narrow_scrollable_view_and_help_return_keep_context(self):
        state=self.detail('FileVault');tui._handle(state,'m',lambda *a:None,None)
        for width,height in [(60,15),(80,24),(120,30)]:
            for _ in range(40):tui._handle(state,tui.curses.KEY_DOWN,lambda *a:None,None)
            frame=build_frame(state,width,height)
            for span in frame.spans:
                self.assertTrue(0<=span.y<height);self.assertLessEqual(span.x+cell_width(span.text),width-1)
            self.assertIn('Esc Back',footer(state,width-4));self.assertIn('? Help',footer(state,width-4))
        tui._handle(state,'?',lambda *a:None,None);tui._handle(state,'?',lambda *a:None,None)
        self.assertEqual(state.overlay,'commands')
