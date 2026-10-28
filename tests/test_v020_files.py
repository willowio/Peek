import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from peekcli.collectors import files
from peekcli.views import select,copy_report


class FilesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()

    def touch(self,relative):
        path=self.root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('contents never searched');return path

    def test_empty_query_never_scans(self):
        with patch.object(files.os,'scandir') as scan:
            self.assertEqual(files.search('').context['state'],'idle')
        scan.assert_not_called()

    def test_default_common_folders_include_nested_matches_not_the_rest_of_home(self):
        expected=[self.touch(name+'/nested/Quarterly Report ü.txt') for name in files.COMMON_FOLDERS]
        self.touch('Library/nested/Quarterly Report.txt');self.touch('other/Quarterly Report.txt')
        found=files.search('quarterly report',home=self.root)
        self.assertEqual(found.context['state'],'complete');self.assertEqual({row['path'] for row in found.data},set(map(str,expected)))
        self.assertEqual(len(found.context['roots']),4)

    def test_custom_recursive_scope_and_literal_unicode_unusual_names(self):
        wanted=[self.touch('chosen/deep/'+name) for name in ['Report ü\nline.txt','Report ? * -live.txt']]
        self.touch('elsewhere/Report.txt')
        found=files.search('REPORT',scope=self.root/'chosen')
        self.assertEqual({row['path'] for row in found.data},set(map(str,wanted)))
        self.assertEqual(files.search('? * -live',scope=self.root/'chosen').data[0]['path'],str(wanted[1]))
        self.assertEqual(files.search('contents never',scope=self.root/'chosen').context['state'],'empty')
        self.assertEqual(files.search('\0',scope=self.root/'chosen').context['state'],'error')

    def test_skip_generated_descendants_and_app_contents_but_not_explicit_root(self):
        for name in ('.git','node_modules','.venv','Caches','build'):
            self.touch(name+'/needle.txt')
        self.touch('Tool.app/Contents/needle.txt');self.touch('normal/needle.txt')
        found=files.search('needle',scope=self.root)
        self.assertEqual([row['path'] for row in found.data],[str(self.root/'normal/needle.txt')])
        self.assertEqual(len(files.search('needle',scope=self.root/'node_modules').data),1)
        self.assertEqual(files.search('needle',scope=self.root/'Tool.app').context['state'],'invalid_scope')
        self.assertTrue(any(c.kind=='applications' for c in files.discover(self.root).candidates))

    def test_directory_links_and_loops_are_not_traversed(self):
        self.touch('real/needle.txt');(self.root/'real/loop').symlink_to(self.root,target_is_directory=True)
        (self.root/'alias').symlink_to(self.root/'real',target_is_directory=True)
        result=files.search('needle',scope=self.root)
        self.assertEqual(len(result.data),1);self.assertLess(result.context['examined'],10)
        self.assertEqual(files.search('needle',scope=self.root/'alias').context['state'],'invalid_scope')

    def test_missing_file_invalid_and_inaccessible_scopes_are_distinct(self):
        path=self.touch('plain.txt')
        for scope in (self.root/'absent',path):self.assertEqual(files.search('x',scope=scope).context['state'],'invalid_scope')
        with patch.object(files.os,'access',return_value=False):
            result=files.search('x',scope=self.root)
        self.assertEqual(result.context['state'],'inaccessible');self.assertTrue(result.errors)
        empty_home=self.root/'empty-home';empty_home.mkdir()
        self.assertEqual(files.search('x',home=empty_home).context['state'],'inaccessible')

    def test_inaccessible_or_disappearing_subfolders_keep_other_matches_and_explain_partial(self):
        self.touch('good/needle.txt');self.touch('blocked/needle.txt');self.touch('gone/needle.txt')
        native=os.scandir
        def scan(path):
            if Path(path).name=='blocked':raise PermissionError('Denied fixture')
            if Path(path).name=='gone':raise FileNotFoundError('Disappeared fixture')
            return native(path)
        with patch.object(files.os,'scandir',side_effect=scan):found=files.search('needle',scope=self.root)
        self.assertEqual(len(found.data),1);self.assertEqual(found.context['state'],'inaccessible');self.assertEqual(found.status,'partial')
        self.assertEqual(len(found.errors),2)

    def test_entry_candidate_memory_depth_time_and_match_limits_are_independent(self):
        for i in range(12):self.touch(f'needle{i}.txt')
        self.touch('deep/deeper/needle.txt')
        for bounds,description in [({'max_entries':3},'entry'),({'max_candidates':2},'candidate'),({'max_memory':1},'memory'),({'max_depth':0},'depth'),({'timeout':0},'time')]:
            result=files.search('needle',scope=self.root,**bounds)
            self.assertEqual(result.context['state'],'limited',bounds)
            self.assertIn(description,' '.join(result.limitations))
        snapshot=files.discover(self.root);found=files.search('needle',scope=self.root,snapshot=snapshot,max_results=2)
        self.assertEqual(len(found.data),2);self.assertEqual(found.context['matches'],13)
        self.assertGreater(found.context['examined'],found.context['matches'])
        self.assertEqual(found.context['state'],'limited')
        absent=files.search('no such name',scope=self.root,max_entries=2)
        self.assertEqual(absent.context['state'],'limited');self.assertFalse(absent.data)

    def test_real_permission_denial_is_handled(self):
        blocked=self.root/'blocked';blocked.mkdir();blocked.chmod(0)
        try:
            if os.access(blocked,os.R_OK|os.X_OK):self.skipTest('Host account bypasses permission bits')
            self.assertEqual(files.search('x',scope=blocked).context['state'],'inaccessible')
        finally:blocked.chmod(0o700)

    def test_snapshot_query_reuse_does_not_scan_or_read_file_contents(self):
        self.touch('deep/First Report.txt');self.touch('deep/Second Report.txt');snapshot=files.discover(self.root)
        with patch.object(files.os,'scandir',side_effect=AssertionError('rescan')),patch.object(Path,'read_text',side_effect=AssertionError('contents')):
            first=files.search('first',scope=self.root,snapshot=snapshot)
            second=files.search('second report',scope=self.root,snapshot=snapshot)
        self.assertEqual(len(first.data),1);self.assertEqual(len(second.data),1)
        self.assertNotEqual(first.data[0]['path'],second.data[0]['path'])

    def test_cancellation_stops_real_traversal(self):
        for i in range(20):self.touch(f'folder{i}/needle.txt')
        event=threading.Event();native=os.scandir;calls=[]
        def scan(path):
            calls.append(str(path))
            if len(calls)==2:event.set()
            return native(path)
        with patch.object(files.os,'scandir',side_effect=scan):snapshot=files.discover(self.root,event)
        self.assertEqual(snapshot.state,'cancelled');self.assertLess(len(calls),20)

    def test_types_metadata_sort_filters_and_copy_scope(self):
        for name in ('Z notes.md','A notes.txt','notes.zip','notes.dmg'):self.touch(name)
        (self.root/'notes.app').mkdir();(self.root/'notes folder').mkdir()
        result=files.search('notes',scope=self.root)
        self.assertEqual(len(select(result,group='documents')),2)
        self.assertEqual(select(result,group='documents')[0]['name'],'A notes.txt')
        self.assertEqual(len(copy_report(result,'all',current=[],selected=None,format='names').splitlines()),6)
        visible=select(result,group='documents')
        self.assertEqual(len(copy_report(result,'current',current=visible,selected=visible[0],format='names').splitlines()),2)
        self.assertEqual(files.inspect_path(str(self.root/'missing')).status,'unavailable')

    def wait_result(self,jobs,token):
        end=time.monotonic()+2
        while time.monotonic()<end:
            for generation,result in jobs.poll():
                if generation==token:return result
            time.sleep(.005)
        self.fail('Search job did not publish latest query')

    def test_jobs_debounce_and_query_changes_reuse_one_real_scan(self):
        self.touch('nested/first.txt');self.touch('nested/second.txt');calls=[]
        def scan(scope,cancel):calls.append(scope);return files.discover(scope,cancel)
        jobs=files.SearchJobs(scan=scan);self.addCleanup(jobs.close)
        jobs.request(1,'first',str(self.root));jobs.request(2,'second',str(self.root))
        jobs.poll();self.assertEqual(calls,[])
        self.assertEqual(self.wait_result(jobs,2).data[0]['name'],'second.txt')
        with patch.object(files.os,'scandir',side_effect=AssertionError('must use cache')):
            jobs.request(3,'first',str(self.root));self.assertEqual(self.wait_result(jobs,3).data[0]['name'],'first.txt')
        self.assertEqual(len(calls),1)

    def test_typing_during_traversal_does_not_cancel_or_restart_scan(self):
        self.touch('nested/second.txt');started=threading.Event();release=threading.Event();calls=[]
        def scan(scope,cancel):
            calls.append(scope);started.set();release.wait(1);self.assertFalse(cancel.is_set());return files.discover(scope,cancel)
        jobs=files.SearchJobs(scan=scan,clock=lambda:10);self.addCleanup(jobs.close)
        with patch.object(files,'DEBOUNCE',0):
            jobs.request(1,'first',str(self.root));jobs.poll();self.assertTrue(started.wait(1))
            jobs.request(2,'second',str(self.root));release.set()
            self.assertEqual(self.wait_result(jobs,2).data[0]['name'],'second.txt')
        self.assertEqual(len(calls),1)

    def test_refresh_and_scope_change_invalidate_cached_candidates(self):
        self.touch('one/old.txt');self.touch('two/new.txt');calls=[]
        def scan(scope,cancel):calls.append(scope);return files.discover(scope,cancel)
        jobs=files.SearchJobs(scan=scan);self.addCleanup(jobs.close)
        jobs.request(1,'old',str(self.root/'one'));self.wait_result(jobs,1)
        self.touch('one/new.txt');jobs.request(2,'new',str(self.root/'one'))
        self.assertEqual(self.wait_result(jobs,2).context['state'],'empty')
        jobs.request(3,'new',str(self.root/'one'),refresh=True);self.assertEqual(len(self.wait_result(jobs,3).data),1)
        jobs.request(4,'new',str(self.root/'two'));self.assertEqual(len(self.wait_result(jobs,4).data),1)
        self.assertEqual(len(calls),3)

    def test_scope_change_cancels_obsolete_worker_and_shutdown_releases_snapshot(self):
        self.touch('next/needle.txt');started=threading.Event();calls=[]
        def scan(scope,cancel):
            calls.append(scope)
            if len(calls)==1:started.set();cancel.wait(1)
            return files.discover(scope,cancel)
        jobs=files.SearchJobs(scan=scan,clock=lambda:10)
        with patch.object(files,'DEBOUNCE',0):
            jobs.request(1,'needle',str(self.root));jobs.poll();self.assertTrue(started.wait(1))
            jobs.request(2,'needle',str(self.root/'next'))
            result=self.wait_result(jobs,2);self.assertEqual(result.data[0]['path'],str(self.root/'next/needle.txt'))
        jobs.close();self.assertIsNone(jobs.cache);self.assertFalse(jobs.worker.is_alive())

    def test_worker_errors_are_visible_and_no_external_search_dependency_exists(self):
        jobs=files.SearchJobs(scan=lambda *args:(_ for _ in ()).throw(OSError('fixture failure')))
        self.addCleanup(jobs.close);jobs.request(1,'x',str(self.root))
        self.assertEqual(self.wait_result(jobs,1).context['state'],'error')
        source=Path(files.__file__).read_text()
        self.assertNotIn('subprocess',source)

    def test_default_common_folder_on_another_volume_is_not_traversed(self):
        from types import SimpleNamespace
        self.touch('Documents/needle.txt');wanted=self.touch('Projects/needle.txt')
        original=Path.lstat
        def metadata(path):
            info=original(path)
            if path==self.root/'Documents':return SimpleNamespace(st_mode=info.st_mode,st_dev=info.st_dev+1)
            return info
        with patch.object(Path,'lstat',metadata):found=files.search('needle',home=self.root)
        self.assertEqual([row['path'] for row in found.data],[str(wanted)])
        self.assertIn('Mounted common folder excluded',' '.join(found.errors))

    def test_type_filter_matches_cached_candidates_before_display_cap_and_preserves_copy(self):
        from dataclasses import replace
        from peekcli import tui
        from peekcli.screens import group_options
        for i in range(files.MAX_RESULTS+8):(self.root/f'needle-folder-{i:04}').mkdir()
        document=self.touch('needle-document.txt')
        original=files.discover(self.root)
        # Deliberately put the rarer type after the entire unfiltered display cap.
        snapshot=replace(original,candidates=tuple(sorted(original.candidates,key=lambda c:c.kind=='documents')))
        unfiltered=files.search('needle',scope=self.root,snapshot=snapshot)
        self.assertFalse(select(unfiltered,group='documents'))
        native=files.file_record
        with patch.object(files.os,'scandir',side_effect=AssertionError('must not rescan')),patch.object(files,'file_record',wraps=native) as metadata:
            filtered=files.search('needle',scope=self.root,snapshot=snapshot,group='documents')
        visible=select(filtered,group='documents')
        self.assertEqual([row['path'] for row in visible],[str(document)])
        self.assertEqual(len(filtered.data),files.MAX_RESULTS)
        self.assertLessEqual(metadata.call_count,2*files.MAX_RESULTS)
        self.assertEqual(filtered.context['memory_bytes'],snapshot.memory_bytes)
        self.assertEqual(filtered.status,'partial');self.assertIn('Displayed-match limit',' '.join(filtered.limitations))
        self.assertEqual(copy_report(filtered,'all',current=visible,selected=visible[0],format='names'),copy_report(unfiltered,'all',current=[],selected=None,format='names'))
        self.assertEqual(copy_report(filtered,'current',current=visible,selected=visible[0],format='names'),'needle-document.txt')
        self.assertIn(str(document),copy_report(filtered,'selected',current=visible,selected=visible[0]))
        self.assertIn('needle-document.txt',copy_report(filtered,'current',current=visible,selected=visible[0],format='tsv'))
        state=tui.State();state.section=2;state.results['files']=filtered;state.view.group='documents'
        self.assertIn(('documents','Documents (1)'),group_options(state))
        self.assertIn(('folders',f'Folders ({files.MAX_RESULTS+8})'),group_options(state))
        folders=files.search('needle',scope=self.root,snapshot=snapshot,group='folders')
        self.assertEqual(len(select(folders,group='folders')),files.MAX_RESULTS);self.assertEqual(folders.status,'partial')

    def test_filter_change_reuses_snapshot_and_prepares_actual_filtered_path_actions(self):
        from peekcli import actions
        self.touch('nested/needle.txt');(self.root/'needle-folder').mkdir();calls=[]
        def scan(scope,cancel):calls.append(scope);return files.discover(scope,cancel)
        jobs=files.SearchJobs(scan=scan,prepare=actions.prepare_result);self.addCleanup(jobs.close)
        jobs.request(1,'needle',str(self.root));self.wait_result(jobs,1)
        with patch.object(files.os,'scandir',side_effect=AssertionError('filter must use cache')),patch.object(actions.platform,'system',return_value='Darwin'):
            jobs.request(2,'needle',str(self.root),group='documents')
            found=self.wait_result(jobs,2)
        visible=select(found,group='documents')
        self.assertEqual(len(calls),1);self.assertEqual(len(visible),1)
        self.assertTrue(visible[0]['_actions']['paths']);self.assertIsNone(visible[0]['_actions']['open'])

    def test_refresh_preserves_selected_candidate_even_if_new_entries_push_it_past_cap(self):
        from dataclasses import replace
        for i in range(files.MAX_RESULTS+1):self.touch(f'needle-{i:04}.txt')
        original=files.discover(self.root)
        candidates=tuple(sorted(original.candidates,key=lambda candidate:candidate.path))
        snapshot=replace(original,candidates=candidates)
        retained=candidates[-1].path
        self.assertNotIn(retained,[row['path'] for row in files.search('needle',scope=self.root,snapshot=snapshot).data])
        for group in ('all','documents'):
            fresh=files.search('needle',scope=self.root,snapshot=snapshot,group=group,selected_path=retained)
            visible=select(fresh,group=group)
            self.assertEqual(len(visible),files.MAX_RESULTS)
            self.assertIn(retained,[row['path'] for row in visible]);self.assertEqual(fresh.status,'partial')
