import unittest
from peekcli import tui


class QuitKeyTests(unittest.TestCase):
    def test_quit_after_focus_reports_with_caps_or_russian_layout(self):
        for key in ['q','Q','й','Й']:
            state=tui.State()
            for event in '\x1b[O\x1b[I':
                self.assertTrue(tui._handle(state,event,lambda *args:None,None))
            self.assertFalse(tui._handle(state,key,lambda *args:None,None),key)

    def test_quit_variants_keep_search_input_literal_and_modal_back_behavior(self):
        for key in ['q','Q','й','Й']:
            state=tui.State();state.search=True
            self.assertTrue(tui._handle(state,key,lambda *args:None,None))
            self.assertEqual(state.view.query,key)
            state=tui.State();state.overlay='help'
            self.assertTrue(tui._handle(state,key,lambda *args:None,None));self.assertEqual(state.overlay,'')
            state=tui.State();state.detail={'name':'Example'}
            self.assertTrue(tui._handle(state,key,lambda *args:None,None));self.assertIsNone(state.detail)
