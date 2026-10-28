"""Confirm removal of a complete, positively identified Peek installation."""
import sys
from .installation import verify, remove
from .strings import text as tr
from .text import safe



def uninstall() -> int:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print('peek gtfo needs an interactive terminal to confirm removal. Nothing was removed.',file=sys.stderr)
        return 1
    t=tr
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
            print(t('kept'));return 0
        if answer=='y':break
        print(t('remove_invalid'))
    try:remove(plan)
    except KeyboardInterrupt:
        print('Removal interrupted; the verified installation may be partly removed. Review its remaining targets.',file=sys.stderr);return 130
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print(t('remove_failed')+' '+safe(exc),file=sys.stderr);return 1
    print(t('removed'))
    return 0
