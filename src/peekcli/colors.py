"""Peek semantic palette for terminal output."""

from __future__ import annotations

import os

RGB = {
    "background": "#171923",
    "surface": "#242635",
    "secondary": "#2C2E3E",
    "border": "#626578",
    "text": "#F2F8FF",
    "selection": "#393B4B",
    "muted": "#A2A5B8",
    "logo": "#D0B9EE",
    "mint": "#A8E6B2",
    "cyan": "#72DCE5",
    "purple": "#D0B9EE",
    "pink": "#F29BA5",
    "orange": "#EBCB85",
    "yellow": "#EBCB85",
    "red": "#F29BA5",
}

# Nearest xterm-256 colors for curses terminals. Curses has no portable RGB
# color-pair API; the RGB values above remain authoritative for ANSI output.
XTERM256 = {
    "background": 235,
    "surface": 236,
    "secondary": 237,
    "border": 60,
    "text": 255,
    "selection": 237,
    "muted": 248,
    "logo": 182,
    "mint": 151,
    "cyan": 116,
    "purple": 146,
    "pink": 181,
    "orange": 180,
    "yellow": 186,
    "red": 174,
}


def supports_truecolor(stream) -> bool:
    if not stream.isatty() or "NO_COLOR" in os.environ:
        return False
    term = os.environ.get("TERM", "").casefold()
    color_term = os.environ.get("COLORTERM", "").casefold()
    return term not in {"", "dumb"} and (
        "truecolor" in color_term or "24bit" in color_term
        or any(name in term for name in ("ghostty", "kitty", "wezterm", "alacritty", "foot"))
    )


def paint(text: str, role: str, *, enabled: bool) -> str:
    """Apply a truecolor foreground without changing the terminal background."""
    if not enabled:
        return text
    hex_color = RGB[role].lstrip("#")
    red, green, blue = (int(hex_color[index:index + 2], 16) for index in (0, 2, 4))
    return f"\033[38;2;{red};{green};{blue}m{text}\033[0m"


# Every ordinary pair uses the terminal background and native text color.
PALETTE = {'text':-1, 'muted':-1, 'border':244, 'logo':182, 'cyan':116, 'mint':151, 'yellow':180, 'red':174}

# Only focused controls own a background: bright text on a subdued lavender slate.
SELECTION_COLORS = (234, 146)
