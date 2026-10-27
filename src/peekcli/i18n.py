"""Static offline catalogs. Identifiers, paths, vendor names and raw evidence stay intact."""
import json
import locale
import os
from importlib.resources import files
from functools import lru_cache

LANGUAGES={'en':'English','pl':'Polski','de':'Deutsch','fr':'Français','es':'Español','pt_BR':'Português (Brasil)','ru':'Русский'}

@lru_cache(maxsize=7)
def catalog(language):
    return json.loads(files('peekcli').joinpath('locales', (language if language in LANGUAGES else 'en')+'.json').read_text(encoding='utf-8'))


def resolve(language='auto'):
    if language in LANGUAGES:
        return language
    raw=os.environ.get('PEEK_LANG') or os.environ.get('LC_ALL') or os.environ.get('LC_MESSAGES') or os.environ.get('LANG')
    if not raw:
        raw=locale.getlocale()[0] or 'en'
    raw=raw.split('.')[0].replace('-','_')
    if raw.lower().startswith('pt'):
        return 'pt_BR'
    return raw.split('_')[0] if raw.split('_')[0] in LANGUAGES else 'en'


def tr(key, language='auto', **values):
    template=catalog(resolve(language)).get(key,catalog('en').get(key,key))
    return template.format(**values)
