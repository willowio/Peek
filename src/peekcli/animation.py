"""Small, best-effort terminal animations for interactive outcomes."""

from __future__ import annotations

import sys
import os
import time

from .colors import paint, supports_truecolor

_FRAMES = {
    "rain": (" .  |   . ", " |  .  |  ", "  | . | . ", " . |   |  "),
    "confetti": (" *  .  +  ", " . +  * ! ", " +  ! . * ", " ! *  + . "),
}
_ROLES = {"rain": "cyan", "confetti": "mint"}
_FRAME_DELAY = 0.035


def animations_enabled() -> bool:
    return not ('NO_COLOR' in os.environ or os.environ.get('PEEK_NO_MOTION') == '1'
                or os.environ.get('PEEK_REDUCED_MOTION') == '1'
                or os.environ.get('TERM', '') in {'', 'dumb'})


def animate_terminal(kind: str, stream=None) -> bool:
    """Play a brief animation on a TTY; return False if skipped or interrupted."""
    if kind not in _FRAMES:
        raise ValueError(f"Unknown terminal animation: {kind}")
    stream = sys.stdout if stream is None else stream
    if not stream.isatty() or not animations_enabled():
        return False

    interrupted = False
    width = max(map(len, _FRAMES[kind]))
    try:
        for index, frame in enumerate(_FRAMES[kind]):
            role = ('logo', 'cyan', 'mint', 'logo')[index % 4] if kind == 'confetti' else _ROLES[kind]
            stream.write("\r" + paint(frame, role, enabled=supports_truecolor(stream)))
            stream.flush()
            time.sleep(_FRAME_DELAY)
    except KeyboardInterrupt:
        interrupted = True
    finally:
        stream.write("\r" + " " * width + "\r")
        stream.flush()
    return not interrupted


class Timeline:
    """Nonblocking, deterministic shared timing for intro and short UI transitions."""
    def __init__(self, kind, mode='subtle', started=None):
        self.kind = kind
        self.started = time.monotonic() if started is None else started
        self.duration = (1.8 if mode == 'full' else 1.35) if kind == 'intro' else (.20 if mode == 'full' else .10)

    def progress(self, clock=None):
        return min(1., max(0., ((time.monotonic() if clock is None else clock) - self.started) / self.duration))

    def active(self, clock=None):
        return self.progress(clock) < 1
