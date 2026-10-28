"""Terminal-safe text and cell-aware clipping shared by reports and curses."""
import unicodedata


def safe(value, *, tabs=False) -> str:
    clean = "".join(ch if ch in "\n\t" or not unicodedata.category(ch).startswith("C") else "?"
                   for ch in str(value))
    return clean if tabs else clean.replace("\t", "    ")


def cell_width(value: str) -> int:
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in {"W", "F"} else 1
               for c in value)


def clip(value, width: int) -> str:
    value = safe(value).replace("\n", " ")
    if width <= 0:
        return ""
    if cell_width(value) <= width:
        return value
    result, used = "", 0
    for char in value:
        n = cell_width(char)
        if used + n > width - 1:
            break
        result += char
        used += n
    return result + "…"


def pad(value, width: int) -> str:
    value = clip(value, width)
    return value + " " * max(0, width - cell_width(value))
