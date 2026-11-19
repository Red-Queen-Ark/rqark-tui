"""Fenced code block rendering for the transcript.

Rich already highlights fenced blocks through :class:`rich.syntax.Syntax`, but
it hands Pygments the fence info string verbatim: a language Pygments does not
know (``jsonc``, ``mjs``, ``console``) silently renders as an unhighlighted
block, and a built-in style paints a panel colour of its own. This module
resolves the fence language and builds the Pygments style from the active
theme's ``code_*`` tokens, so a fence either highlights properly or reads as
plain text, and its panel always matches the transcript.
"""

import re
from functools import cache

from pygments.lexers import get_lexer_by_name
from pygments.style import Style as PygmentsStyle
from pygments.token import Comment, Generic, Keyword, Name, Number, Operator, Punctuation, String
from pygments.token import Text as TokenText
from pygments.util import ClassNotFound
from rich.markdown import Markdown
from rich.syntax import PygmentsSyntaxTheme, SyntaxTheme

from rqark_tui.tui.theme import Theme, active_theme, load_theme


@cache
def _build_style(name: str) -> type[PygmentsStyle]:
    """Build the Pygments style class for the theme called ``name``."""
    theme: Theme = active_theme() if active_theme().name == name else load_theme(name)
    color = theme.color
    return type(
        f'Rqark{name.title()}Style',
        (PygmentsStyle,),
        {
            'background_color': color('code_bg'),
            'default_style': color('code_text'),
            'styles': {
                TokenText: color('code_text'),
                Comment: f'italic {color("code_comment")}',
                Comment.Preproc: color('code_keyword'),
                Keyword: f'bold {color("code_keyword")}',
                Keyword.Type: color('code_keyword'),
                Operator: color('code_operator'),
                Operator.Word: color('code_keyword'),
                Punctuation: color('code_text'),
                Name: color('code_name'),
                Name.Attribute: color('code_name'),
                Name.Builtin: color('code_keyword'),
                Name.Class: f'bold {color("code_name")}',
                Name.Function: f'bold {color("code_name")}',
                Name.Tag: color('code_keyword'),
                Name.Variable: color('code_name'),
                Number: color('code_number'),
                String: color('code_string'),
                String.Doc: f'italic {color("code_string")}',
                String.Escape: color('code_keyword'),
                Generic.Deleted: color('diff_del'),
                Generic.Inserted: color('diff_add'),
                Generic.Heading: f'bold {color("code_name")}',
                Generic.Emph: f'italic {color("code_text")}',
                Generic.Strong: f'bold {color("code_text")}',
            },
        },
    )


@cache
def code_theme(name: str | None = None) -> SyntaxTheme:
    """Rich's syntax theme built from the theme called ``name``.

    ``None`` means the active theme.
    """
    return PygmentsSyntaxTheme(_build_style(name or active_theme().name))


class ThemedMarkdown(Markdown):
    """A :class:`rich.markdown.Markdown` whose code blocks use a theme's palette.

    ``Markdown`` only takes a style *name*, which would mean registering our
    style class in Pygments' global registry. Assigning the theme after
    construction reaches the same render path, since ``Markdown`` only reads
    ``code_theme`` when it builds each code block.
    """

    def __init__(self, markup: str, theme: SyntaxTheme) -> None:
        super().__init__(markup)
        self.code_theme = theme
        self.inline_code_theme = theme


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
    return ThemedMarkdown(normalise_fences(text), code_theme())
