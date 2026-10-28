import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from peekcli.collectors import apps, services, collect_all
from peekcli import collectors, animation, tui, maintenance
from peekcli.models import Result
from peekcli.system import Command
from peekcli.views import select, copy_report


class Edges(unittest.TestCase):
    def test_external_plist_symlinks_are_not_read(self):
        import plistlib
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'A.app'; (root/'Contents').mkdir(parents=True)
            outside=Path(temp)/'outside.plist'; outside.write_bytes(plistlib.dumps({'Secret':'private'}))
            (root/'Contents/Info.plist').symlink_to(outside)
            result=apps.inspect_bundle(str(root),plist=True)
            self.assertEqual(result.status,'partial')
            self.assertNotIn('info_plist',result.data)
            self.assertNotIn('private',str(result.data))

    def test_full_plist_has_a_size_limit(self):
        import plistlib
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'A.app'; (root/'Contents').mkdir(parents=True)
            (root/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleName':'A','Large':'x'*262144}))
            result=apps.inspect_bundle(str(root),plist=True)
            self.assertEqual(result.status,'partial')
            self.assertIn('256 KiB',result.errors[0])

    def test_broken_and_looping_application_links_remain_unknown_candidates(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/'broken.app').symlink_to(root/'absent.app')
            (root/'loop.app').symlink_to(root/'loop.app')
            with patch.object(apps.platform,'system',return_value='Darwin'):
                result=apps.collect(roots=[root])
            self.assertEqual(result.status,'partial')
            self.assertEqual(len(result.data),2)
            self.assertTrue(all(x['ownership']=='unknown' for x in result.data))

    def test_missing_dependency_flag_does_not_imply_dependency(self):
        result=Result('brew','ok',{'formulae':[{'name':'old','requested':False}], 'casks':[], 'taps':[]})
        self.assertEqual(select(result,group='dependency'),[])
        self.assertIn('unavailable',copy_report(result,'dependency',current=[],selected=None))

    def test_one_failed_collector_preserves_other_sections(self):
        def bad(): raise PermissionError('denied')
        with patch.object(collectors,'COLLECTORS',{'apps':bad,'brew':lambda:Result('brew','ok',{'formulae':[],'casks':[],'taps':[]})}):
            results=collect_all()
        self.assertEqual([r.status for r in results],['error','ok'])
        self.assertIn('denied',results[0].errors[0])


    def test_reduced_color_terminal_uses_only_valid_pairs_and_colors(self):
        with patch.dict(os.environ,{},clear=True),patch.object(tui.curses,'has_colors',return_value=True),patch.object(tui.curses,'start_color'),patch.object(tui.curses,'use_default_colors'),patch.object(tui.curses,'COLORS',8,create=True),patch.object(tui.curses,'COLOR_PAIRS',8,create=True),patch.object(tui.curses,'init_pair') as pair:
            tui._init_colors()
        for call in pair.call_args_list:
            number,fg,bg=call.args
            self.assertLess(number,8)
            self.assertTrue(-1<=fg<8)
            self.assertTrue(-1<=bg<8)

    def test_disabled_state_is_observed_separately_from_plist_configuration(self):
        item={'label':'org.test','kind':'System Launch Daemon','configured_disabled':False}
        with patch.object(services,'run',side_effect=[Command(stdout='state = waiting\n'),Command(stdout='disabled services = {\n "org.test" => true\n}\n')]):
            r=services.inspect_service(item)
        self.assertTrue(r.data['disabled'])
        self.assertFalse(r.data['running'])
        self.assertTrue(r.data['loaded'])
        self.assertFalse(r.data['configured_disabled'])



    def test_app_inspection_does_not_escape_internal_executable_symlinks(self):
        import plistlib
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'A.app'; (root/'Contents/MacOS').mkdir(parents=True)
            (root/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable':'program'}))
            (root/'Contents/MacOS/program').symlink_to('/bin/sh')
            with patch.object(apps.platform,'system',return_value='Darwin'),patch.object(apps,'run') as command:
                r=apps.inspect_bundle(str(root))
            command.assert_not_called()
            self.assertEqual(r.data['architectures'],'Unknown / unavailable')


if __name__=='__main__':unittest.main()
