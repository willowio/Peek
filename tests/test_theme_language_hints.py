import unittest
from peekcli import tui
from peekcli.screens import footer
from peekcli.text import cell_width

class FooterHintTests(unittest.TestCase):
    def test_contextual_hints_always_fit_and_keep_help_discoverable(self):
        state=tui.State()
        for overlay in ('','filter','copy','help','diagnostics','evidence'):
            state.overlay=overlay
            for width in (56,76,96,116,156):
                value=footer(state,width);self.assertIn('?',value);self.assertLessEqual(cell_width(value),width)
                self.assertNotIn('Settings',value);self.assertNotIn('Replay',value)
