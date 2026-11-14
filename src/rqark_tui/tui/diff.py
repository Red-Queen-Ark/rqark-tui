"""Unified diff rendering for tool results.

Edit and patch tools answer with a unified diff. Rendered as one dim blob the
``+``/``-`` prefix is the only signal that a line was added or removed, so a
multi-hunk patch reads as wall of text. This module detects that shape and
paints it with dedicated colours, hunk separators and file markers, leaving
every other tool result to the plain renderer.

The colours are module constants until the theme module (issue #26) supplies
``diff_add`` / ``diff_del`` / ``diff_hunk``; the names here match those tokens
so the move is a rename.
"""

import re

from rich.style import Style
from rich.text import Text

DIFF_ADD = '#87d787'

DIFF_DEL = '#ff5f5f'

DIFF_HUNK = '#5f87af'

DIFF_META = '#757575'

DIFF_CONTEXT = '#9e9e9e'

#: Rows a single patch may render. A generated lockfile diff runs to thousands
#: of lines; rows past this point are dropped from the render (the copy buffer
#: still holds the whole patch).
MAX_LINES = 400

_HUNK = re.compile(r'^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@')

_PREAMBLE = ('diff --git ', 'diff --cc ', 'diff --combined ', 'index ', 'new file mode ', 'deleted file mode ', 'old mode ', 'new mode ', 'similarity index ', 'dissimilarity index ', 'rename from ', 'rename to ', 'Binary files ')

_ROW_STYLES = (('+', DIFF_ADD), ('-', DIFF_DEL))


def looks_like_diff(text: str) -> bool:
    """Whether ``text`` is a unified diff rather than ordinary tool output.

    A hunk header alone is not enough: prose can quote ``@@``. The body must
    also carry a ``---`` and a ``+++`` file header before a hunk.
    """
    headers = 0
    for line in text.splitlines():
        if _HUNK.match(line):
            if headers >= 2:
                return True
            continue
        if line.startswith(('--- ', '+++ ')):
            headers += 1
    return False


def _file_path(header: str) -> str:
    path = header.split('\t', 1)[0].strip()
    if path.startswith(('a/', 'b/')):
        return path[2:]
    return path


def _rows(text: str) -> list[tuple[str, str]]:
    lines = text.splitlines()
    files = sum(1 for line in lines if line.startswith('+++ '))
    rows: list[tuple[str, str]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        following = lines[index + 1] if index + 1 < len(lines) else ''
        if line.startswith('--- ') and following.startswith('+++ '):
            if files > 1:
                rows.append((_file_path(following[4:]), DIFF_META))
            index += 2
            continue
        if line.startswith(_PREAMBLE):
            index += 1
            continue
        if line.startswith('@@'):
            rows.append((line, DIFF_HUNK))
        elif line.startswith('\\'):
            rows.append((line, DIFF_META))
        else:
            rows.append((line, _row_colour(line)))
        index += 1
    return rows


def _row_colour(line: str) -> str:
    for prefix, colour in _ROW_STYLES:
        if line.startswith(prefix):
            return colour
    return DIFF_CONTEXT


def render(text: str) -> Text:
    """Render a unified diff for the transcript, capped at :data:`MAX_LINES` rows."""
    rows = _rows(text)
    hidden = len(rows) - MAX_LINES
    if hidden > 0:
        rows = [*rows[:MAX_LINES], (f'… {hidden} more line(s), copy for the full patch', DIFF_META)]
    out = Text()
    for position, (content, colour) in enumerate(rows):
        if position:
            out.append('\n')
        out.append(content, Style(color=colour))
    return out
