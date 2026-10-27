import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from peekcli import settings,tui
from peekcli.i18n import resolve,tr
from peekcli.models import Result
from peekcli.screens import footer
from peekcli.text import cell_width


class ThemeLanguageHintTests(unittest.TestCase):
    def test_removed_themes_load_as_default_without_rewriting(self):
        self.assertNotIn('theme',settings.CHOICES)
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'PEEK_CONFIG':temp+'/settings.json'}):
            p=Path(temp)/'settings.json'
            for name in ['dark','midnight','clean','light']:
                original=json.dumps({'theme':name,'language':'pl'});p.write_text(original)
                prefs,error=settings.load();self.assertFalse(error);self.assertFalse(hasattr(prefs,'theme'));self.assertEqual(prefs.language,'pl');self.assertEqual(p.read_text(),original)

    def test_supported_language_auto_detection_and_persistence(self):
        with patch.dict(os.environ,{'LC_ALL':'pl_PL.UTF-8'},clear=True):self.assertEqual(resolve(),'pl')
        self.assertEqual(tr('settings','pl'),'Ustawienia')
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'PEEK_CONFIG':temp+'/settings.json'}):
            settings.save(settings.Preferences(language='pl'));self.assertEqual(settings.load()[0].language,'pl')

    def test_footer_keeps_settings_available_and_submenus_contextual(self):
        for language in ['en','pl','de','pt_BR']:
            state=tui.State(preferences=settings.Preferences(language=language))
            for width in [56,76,96,116,156]:
                text=footer(state,width);self.assertIn(', '+state.t('settings'),text);self.assertEqual(text.count(', '+state.t('settings')),1);self.assertLessEqual(cell_width(text),width)
            state.results['apps']=Result('apps','partial',[],errors=['limited'])
            self.assertNotIn('d '+state.t('diagnostics'),footer(state,156))
            for overlay in ['settings','filter','help','diagnostics','evidence']:
                state.overlay=overlay;text=footer(state,156)
                self.assertNotIn(', '+state.t('settings'),text)
                self.assertNotIn('r '+state.t('refresh'),text)
                self.assertLessEqual(cell_width(text),156)
