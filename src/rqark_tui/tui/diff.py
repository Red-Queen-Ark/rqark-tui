"""Unified diff rendering for tool results.

Edit and patch tools answer with a unified diff. Rendered as one dim blob the
``+``/``-`` prefix is the only signal that a line was added or removed, so a
multi-hunk patch reads as wall of text. This module detects that shape and
paints it with dedicated colours, hunk separators and file markers, leaving
every other tool result to the plain renderer.

The colours come from the active theme's ``diff_*`` tokens.
"""

import difflib
import json
import re

from rich.style import Style
from rich.text import Text

from rqark_tui.tui.theme import active_theme

#: Tools whose arguments carry the change, so a patch can be rebuilt from them.
REBUILDABLE = ('edit_file', 'write_file')


def _colour(token: str) -> str:
    """The active theme's value for ``token``."""
    return active_theme().color(token)


#: Characters a rebuilt patch may hold. The arguments already keep the full text,
#: so a huge write would otherwise be copied twice for a render that folds at
#: :data:`MAX_LINES` anyway.
MAX_REBUILD = 200_000

#: Rows a single patch may render. A generated lockfile diff runs to thousands
#: of lines; rows past this point are dropped from the render (the copy buffer
#: still holds the whole patch).
MAX_LINES = 400

_HUNK = re.compile(r'^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@')

_PREAMBLE = ('diff --git ', 'diff --cc ', 'diff --combined ', 'index ', 'new file mode ', 'deleted file mode ', 'old mode ', 'new mode ', 'similarity index ', 'dissimilarity index ', 'rename from ', 'rename to ', 'Binary files ')

#: Token each side of a changed line is painted with.
_ROW_TOKENS = (('+', 'diff_add'), ('-', 'diff_del'))


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
    rows: list[tuple[str, str]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        following = lines[index + 1] if index + 1 < len(lines) else ''
        if line.startswith('--- ') and following.startswith('+++ '):
            rows.append((_file_path(following[4:]), _colour('diff_meta')))
            index += 2
            continue
        if line.startswith(_PREAMBLE):
            index += 1
            continue
        if line.startswith('@@'):
            rows.append((line, _colour('diff_hunk')))
        elif line.startswith('\\'):
            rows.append((line, _colour('diff_meta')))
        else:
            rows.append((line, _row_colour(line)))
        index += 1
    return rows


def _row_colour(line: str) -> str:
    for prefix, token in _ROW_TOKENS:
        if line.startswith(prefix):
            return _colour(token)
    return _colour('diff_context')


def from_arguments(name: str, arguments: str) -> str | None:
    """Rebuild the change an edit or write call made from its arguments.

    Those tools answer with a verdict (``Successfully edited src/a.py``), so the
    patch is reconstructed from the arguments: ``old_string`` and ``new_string``
    for an edit, ``content`` for a write that replaced a file wholesale.
    """
    try:
        data = json.loads(arguments)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    path = data.get('path')
    label = path if isinstance(path, str) and path else name
    before = data.get('old_string')
    after = data.get('new_string')
    if isinstance(before, str) and isinstance(after, str) and before != after and len(before) + len(after) <= MAX_REBUILD:
        patch = list(difflib.unified_diff(before.splitlines(), after.splitlines(), fromfile=f'a/{label}', tofile=f'b/{label}', lineterm=''))
        return '\n'.join(patch) if patch else None
    content = data.get('content')
    if name == 'write_file' and isinstance(content, str) and content.strip() and len(content) <= MAX_REBUILD:
        body = content.rstrip('\n').splitlines()
        rows = [f'--- a/{label}', f'+++ b/{label}', f'@@ -0,0 +1,{len(body)} @@', *(f'+{line}' for line in body)]
        return '\n'.join(rows)
    return None


def counts(text: str) -> tuple[int, int]:
    """Added and removed line counts of a patch.

    The ``---``/``+++`` pair is skipped as a pair: a removed line can begin with
    ``--``, which on its own reads like a file header.
    """
    lines = text.splitlines()
    added = removed = 0
    index = 0
    while index < len(lines):
        line = lines[index]
        following = lines[index + 1] if index + 1 < len(lines) else ''
        if line.startswith('--- ') and following.startswith('+++ '):
            index += 2
            continue
        if not _HUNK.match(line):
            if line.startswith('+'):
                added += 1
            elif line.startswith('-'):
                removed += 1
        index += 1
    return added, removed


def render(text: str) -> Text:
    """Render a unified diff for the transcript, capped at :data:`MAX_LINES` rows."""
    rows = _rows(text)
    hidden = len(rows) - MAX_LINES
    if hidden > 0:
        rows = [*rows[:MAX_LINES], (f'… {hidden} more line(s), copy for the full patch', _colour('diff_meta'))]
    out = Text()
    for position, (content, colour) in enumerate(rows):
        if position:
            out.append('\n')
        out.append(content, Style(color=colour))
    return out
