"""The owner's peek.txt is packaged unchanged as the single canonical wordmark."""
from importlib.resources import files


def load_artwork(name):
    return files('peekcli').joinpath(name).read_text(encoding='utf-8').rstrip('\n')


WORDMARK = load_artwork('wordmark.txt')
# Compatibility imports reference the same asset, never a second decorative logo.
COMPACT_WORDMARK = tuple(WORDMARK.splitlines())
ASCII_WORDMARK = COMPACT_WORDMARK
UNINSTALL_ART = 'Peek / maintenance'
TAGLINE = 'take a look around.'
