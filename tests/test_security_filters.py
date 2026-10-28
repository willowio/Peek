import unittest
from unittest.mock import patch
from peekcli import tui
from peekcli.collectors import security
from peekcli.models import Result
from peekcli.system import Command
from peekcli.screens import group_options,detail_lines
from peekcli.views import copy_scopes
from peekcli.strings import text as tr


class SecurityFilterCleanupTests(unittest.TestCase):
    def test_removed_filters_are_absent_from_filter_and_copy_choices(self):
        for section,data in [('apps',[]),('brew',{'formulae':[{'name':'tool','requested':None,'dependency':None}]}),('security',[]),('services',{'launch_items':[]})]:
            state=tui.State();state.section=next(i for i,(_,key) in enumerate(tui.MENU) if key==section)
            state.results[section]=Result(section,'ok',data)
            self.assertNotIn('unknown',dict(group_options(state)))
            self.assertNotIn('unknown',dict(copy_scopes(state.results[section])))
            if section=='brew':
                self.assertNotIn('dependency',dict(group_options(state)))
                self.assertNotIn('dependency',dict(copy_scopes(state.results[section])))
                self.assertNotIn('requested',dict(group_options(state)))

    def test_dependency_placeholders_removed_but_evidence_preserved(self):
        row={'name':'tool','kind':'formula','dependencies':[],'dependencies_collected':False,'requested':None}
        lines='\n'.join(line for line,_ in detail_lines(row,'brew',tr))
        self.assertNotIn('Dependencies',lines);self.assertNotIn('not recorded',lines);self.assertNotIn('Not collected',lines)
        self.assertIn('dependencies_collected',row)

    def test_firewall_additions_are_read_only_and_failures_not_inferred(self):
        for name,flag,output in [('Firewall Stealth','--getstealthmode','Firewall stealth mode is off'),('Firewall Block All','--getblockall','Firewall has block all state set to disabled.')]:
            with patch.object(security,'find_executable',return_value='/usr/libexec/ApplicationFirewall/socketfilterfw'),patch.object(security,'run',return_value=Command(stdout=output)) as run:
                row=security.check(name,['/usr/libexec/ApplicationFirewall/socketfilterfw',flag],('enabled','mode is on'),('disabled','mode is off'))
            self.assertEqual(row['state'],'Disabled');self.assertEqual(run.call_args.args[0][-1],flag)
            with patch.object(security,'find_executable',return_value='/native'),patch.object(security,'run',return_value=Command(stdout='enabled',returncode=1)):
                self.assertEqual(security.check(name,['/native',flag],('enabled',),('disabled',))['state'],'Error')
