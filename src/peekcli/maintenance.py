"""Confirm removal of a complete, positively identified Peek installation."""
import sys
from .animation import animate_terminal
from .installation import verify, remove
from .settings import load
from .i18n import tr
from .text import safe


def _animate(kind):
    try:animate_terminal(kind,sys.stdout)
    except (OSError,KeyboardInterrupt):pass


def uninstall() -> int:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print('peek gtfo needs an interactive terminal to confirm removal. Nothing was removed.',file=sys.stderr)
        return 1
    t=lambda key:tr(key,load()[0].language)
    try:plan=verify()
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print(t('remove_failed')+' '+safe(exc),file=sys.stderr)
        return 1
    print('Peek · '+t('uninstall'))
    print(t('targets')+':\n  '+safe(plan['prefix'])+'\n  '+safe(plan['launcher']))
    print(t('preserved'))
    while True:
        try:answer=input(t('remove_prompt')).strip().casefold()
        except EOFError:
            print('\n'+t('kept'));return 0
        except KeyboardInterrupt:
            print('\n'+t('kept'));return 130
        if answer in {'','n'}:
            _animate('confetti');print(t('kept'));return 0
        if answer=='y':break
        print(t('remove_invalid'))
    _animate('rain')
    try:remove(plan)
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print(t('remove_failed')+' '+safe(exc),file=sys.stderr);return 1
    print(t('removed'))
    return 0
