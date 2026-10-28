import unittest
from unittest.mock import patch
from peekcli import tui
from peekcli.models import Result
from peekcli.screens import document,footer


class FinderBundleActionTests(unittest.TestCase):
    def test_finder_lowercase_and_uppercase_dispatch_native_action_from_details(self):
        for key in ['f','F']:
            state=tui.State();state.detail={'name':'Example','path':'/Applications/Example.app'};jobs=[]
            with patch.object(tui.actions,'reveal',return_value=Result('finder','ok',{})) as reveal:
                tui._handle(state,key,lambda *args:jobs.append(args),None)
                self.assertEqual(jobs[0][0],'finder');jobs[0][1]()
                reveal.assert_called_once_with('/Applications/Example.app')
            self.assertEqual(state.overlay,'')
        state=tui.State();tui._handle(state,'f',lambda *args:None,None)
        self.assertEqual(state.overlay,'filter')

    def test_bundle_tree_and_technical_evidence_are_distinct(self):
        state=tui.State();state.detail={'name':'Example','path':'/Applications/Example.app','bundle_id':'org.example.app','tree':{'root':'.','entries':[{'path':'Contents/unique-tree-file','type':'file'}],'errors':[],'truncated':False}}
        jobs=[];tui._handle(state,'b',lambda *args:jobs.append(args),None)
        self.assertEqual(state.overlay,'bundle')
        with patch.object(tui,'inspect_bundle',return_value=Result('apps','ok',{})) as inspect:
            jobs[0][1]();self.assertTrue(inspect.call_args.kwargs['tree'])
        tree='\n'.join(text for text,_ in document(state));self.assertIn('unique-tree-file',tree);self.assertNotIn('org.example.app',tree)
        self.assertNotIn('Enter',footer(state,156))
        tui._handle(state,'\x1b',lambda *args:None,None)
        tui._handle(state,'t',lambda *args:None,None)
        self.assertEqual(state.overlay,'evidence')
        evidence='\n'.join(text for text,_ in document(state));self.assertIn('org.example.app',evidence);self.assertNotIn('unique-tree-file',evidence)
