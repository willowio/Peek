from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from peekcli import actions,tui
from peekcli.models import Result
from peekcli.screens import build_frame,footer
from peekcli.system import Command


class PathActionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()
        self.mac=patch.object(actions.platform,'system',return_value='Darwin');self.mac.start();self.addCleanup(self.mac.stop)

    def test_files_never_open_any_kind_or_show_confirmation_even_with_stale_action_cache(self):
        for name in ('doc.txt','folder','App.app','image.dmg','installer.pkg','script.command','archive.zip','binary'):
            path=self.root/name
            path.mkdir() if name in ('folder','App.app') else path.write_text('fixture')
            row=actions.prepare_row({'name':name,'path':str(path)},'files')
            self.assertIsNone(row['_actions']['open'])
            with patch.object(actions,'run') as run:
                self.assertEqual(actions.open_target(row,'files').status,'unavailable')
            run.assert_not_called()
            row['_actions']['open']=('disk_image',str(path))
            state=tui.State();state.section=2;state.results['files']=Result('files','ok',[row]);jobs=[]
            tui._handle(state,'o',lambda *a:jobs.append(a),None)
            self.assertFalse(jobs);self.assertEqual(state.overlay,'');self.assertIsNone(state.confirmation)
            row['_actions']['open']=None
            self.assertNotIn('o Open',footer(state,150))
            self.assertNotIn('o  Open','\n'.join(span.text for span in build_frame(state,120,30).spans))

    def test_finder_reveals_literal_selected_entry_and_symlink_own_location(self):
        path=self.root/'doc ; $(never).txt';path.write_text('x')
        unreadable=self.root/'private.txt';unreadable.write_text('x');unreadable.chmod(0)
        link=self.root/'own alias';link.symlink_to(path)
        broken=self.root/'broken alias';broken.symlink_to(self.root/'gone')
        try:
            for selected in (path,unreadable,link,broken):
                with patch.object(actions,'run',return_value=Command()) as run:
                    self.assertEqual(actions.reveal(str(selected)).status,'ok')
                self.assertEqual(run.call_args.args[0],['/usr/bin/open','-R',str(selected)])
                self.assertTrue(actions.prepare_row({'path':str(selected)},'files')['_actions']['paths'])
        finally:unreadable.chmod(0o600)

    def test_missing_paths_revalidate_and_launch_errors_do_not_disrupt_details(self):
        path=self.root/'gone.txt';path.write_text('x');row=actions.prepare_row({'path':str(path)},'files');path.unlink()
        with patch.object(actions,'run') as run:self.assertEqual(actions.reveal(row['path']).status,'unavailable')
        run.assert_not_called()
        path.write_text('x')
        with patch.object(actions,'run',return_value=Command(returncode=1,stderr='Finder refused')):
            self.assertEqual(actions.reveal(str(path)).status,'error')

    def test_service_plist_and_program_paths_remain_distinct(self):
        plist=self.root/'job.plist';plist.write_text('plist');program=self.root/'tool';program.write_text('tool')
        row=actions.prepare_row({'label':'job','path':str(plist),'program':str(program)},'services')
        self.assertEqual(actions.paths_for(row,'services'),[('Plist',str(plist)),('Program',str(program))])
        state=tui.State();state.section=4;state.detail=row
        tui._handle(state,'x',lambda *a:None,None);self.assertEqual(state.overlay,'paths:copy')

    def test_non_macos_and_missing_paths_disable_reveal(self):
        path=self.root/'doc.txt';path.write_text('x')
        with patch.object(actions.platform,'system',return_value='Linux'):
            self.assertEqual(actions.reveal(str(path)).status,'unavailable')
        row=actions.prepare_row({'path':str(self.root/'missing')},'files')
        self.assertFalse(row['_actions']['paths'])
