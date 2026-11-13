"""Fenced code block rendering for the transcript.

Rich already highlights fenced blocks through :class:`rich.syntax.Syntax`, but
it hands Pygments the fence info string verbatim: a language Pygments does not
know (``jsonc``, ``mjs``, ``console``) silently renders as an unhighlighted
block, and the default ``monokai`` style paints a ``#272822`` panel that does
not match the transcript background. This module resolves the fence language
and pins the style, so a fence either highlights properly or reads as plain
text, never as a half-styled band.
"""

import re

from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound
from rich.markdown import Markdown

#: Pygments style for fenced blocks. ``native`` has a ``#202020`` background,
#: which sits close enough to the ``#141414`` transcript that a code block reads
#: as part of the message instead of a foreign panel.
CODE_THEME = 'native'

#: Fence aliases Pygments does not resolve on its own.
_ALIASES = {
    'mjs': 'javascript',
    'cjs': 'javascript',
    'jsonc': 'json',
    'json5': 'json',
    'patch': 'diff',
    'kt': 'kotlin',
    'txt': 'text',
    'plaintext': 'text',
    'plain': 'text',
    'output': 'text',
    'log': 'text',
    'tree': 'text',
    'env': 'text',
    'dotenv': 'text',
    'make': 'makefile',
    'sh-session': 'console',
}

_FENCE = re.compile(r'^(?P<indent>[ \t]*)(?P<fence>`{3,}|~{3,})(?P<info>[^\s`]*)')


def resolve_language(language: str) -> str:
    """Return a Pygments-resolvable lexer name for ``language``, or ``''``.

    An unknown language resolves to the empty string so the fence renders as
    plain text rather than as an unstyled highlighted block.
    """
    name = _ALIASES.get(language.lower(), language.lower())
    if not name:
        return ''
    try:
        get_lexer_by_name(name)
    except ClassNotFound:
        return ''
    return name


def normalise_fences(text: str) -> str:
    """Rewrite fence info strings in ``text`` to names Pygments resolves.

    Only opening fences are touched: everything between an opening and its
    closing fence is passed through untouched, so a code sample containing
    ``` is not rewritten. A fence with an unknown language keeps its backticks
    and loses the info string.
    """
    out: list[str] = []
    fence_char = ''
    for line in text.split('\n'):
        match = _FENCE.match(line)
        if not fence_char:
            if match is None:
                out.append(line)
                continue
            fence_char = match.group('fence')[0]
            language = resolve_language(match.group('info'))
            out.append(f'{match.group("indent")}{match.group("fence")}{language}')
            continue
        out.append(line)
        if match is not None and match.group('fence')[0] == fence_char and not match.group('info'):
            fence_char = ''
    return '\n'.join(out)


def markdown(text: str) -> Markdown:
    """Build a :class:`rich.markdown.Markdown` for a transcript body."""
    return Markdown(normalise_fences(text), code_theme=CODE_THEME)
