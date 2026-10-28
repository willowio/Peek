"""Nonblocking TUI-only timing; no installer/uninstaller animations."""
import os
import time

def animations_enabled() -> bool:
    return not ('NO_COLOR' in os.environ or os.environ.get('PEEK_NO_MOTION') == '1'
                or os.environ.get('PEEK_REDUCED_MOTION') == '1'
                or os.environ.get('TERM', '') in {'', 'dumb'})



class Timeline:
    """Nonblocking, deterministic shared timing for intro and short UI transitions."""
    def __init__(self, kind, started=None):
        self.kind = kind
        self.started = time.monotonic() if started is None else started
        self.duration = 1.35 if kind == 'intro' else .10

    def progress(self, clock=None):
        return min(1., max(0., ((time.monotonic() if clock is None else clock) - self.started) / self.duration))

    def active(self, clock=None):
        return self.progress(clock) < 1
