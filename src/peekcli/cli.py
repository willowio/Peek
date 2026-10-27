"""The public command opens Peek or its explicitly confirmed uninstaller."""
from __future__ import annotations
import curses
import sys
from .text import safe


def main(argv: list[str] | None = None) -> int:
    args=list(sys.argv[1:] if argv is None else argv)
    if args not in ([], ['gtfo']):
        print('Use peek to open Peek, or peek gtfo to uninstall. Help is inside Peek (?).',file=sys.stderr)
        return 2
    try:
        if args:
            from .maintenance import uninstall
            return uninstall()
        from .tui import can_launch, run
        if not can_launch(sys.stdout,sys.stdin):
            print('Peek needs an interactive terminal. Open a terminal window and run peek.',file=sys.stderr)
            return 1
        run()
        return 0
    except KeyboardInterrupt:
        return 130
    except (OSError,ValueError,curses.error) as exc:
        print(f'Peek could not open: {safe(exc)}',file=sys.stderr)
        return 1


if __name__=='__main__':raise SystemExit(main())
