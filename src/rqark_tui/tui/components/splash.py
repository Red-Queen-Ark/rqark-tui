"""The wordmark shown while the session on screen has nothing in it.

A brand-new session used to open onto an empty transcript, which reads as a
broken window rather than a fresh start. The splash fills that area with the
product name until the first message arrives.
"""

from rich.text import Text
from textual.widgets import Static

from rqark_tui.tui.theme import active_theme

GLYPH_ROWS = 5
GLYPH_WIDTH = 4

_GLYPHS: dict[str, tuple[str, ...]] = {
    'A': (' ██ ', '█  █', '████', '█  █', '█  █'),
    'D': ('███ ', '█  █', '█  █', '█  █', '███ '),
    'E': ('████', '█   ', '███ ', '█   ', '████'),
    'K': ('█  █', '█ █ ', '██  ', '█ █ ', '█  █'),
    'N': ('█  █', '██ █', '█ ██', '█  █', '█  █'),
    'Q': (' ██ ', '█  █', '█  █', '█ ██', ' ██ '),
    'R': ('███ ', '█  █', '███ ', '█ █ ', '█  █'),
    'U': ('█  █', '█  █', '█  █', '█  █', ' ██ '),
    ' ': ('    ', '    ', '    ', '    ', '    '),
}

#: What the splash spells out.
WORDMARK = 'RED QUEEN ARK'

#: Hint under the wordmark.
HINT = 'Type a message to begin'


def glyphs_cover(wordmark: str = WORDMARK) -> bool:
    """Whether every letter of the wordmark has a block glyph."""
    return all(letter in _GLYPHS for letter in wordmark)


def wordmark_lines(wordmark: str = WORDMARK) -> list[str]:
    """The wordmark as block art, one string per row."""
    rows: list[list[str]] = [[] for _ in range(GLYPH_ROWS)]
    missing = (GLYPH_WIDTH * ' ',) * GLYPH_ROWS
    for letter in wordmark:
        glyph = _GLYPHS.get(letter, missing)
        for index, line in enumerate(glyph):
            rows[index].append(line)
    return [' '.join(parts).rstrip() for parts in rows]


def wordmark_width(wordmark: str = WORDMARK) -> int:
    """The columns the block art needs."""
    return max(len(line) for line in wordmark_lines(wordmark))


class Splash(Static):
    """The centred Red Queen Ark wordmark, shown while a session is empty."""

    DEFAULT_CSS = """
    Splash {
        height: 1fr;
        display: none;
        content-align: center middle;
        text-align: center;
    }
    Splash.visible {
        display: block;
    }
    """

    def on_mount(self) -> None:
        self.refresh_wordmark()

    def on_resize(self) -> None:
        self.refresh_wordmark()

    def repaint(self) -> None:
        """Re-render the wordmark after the theme changed."""
        if self.is_mounted:
            self.refresh_wordmark()

    def refresh_wordmark(self) -> None:
        """Paint the art when it fits, plain text when it does not."""
        theme = active_theme()
        width = self.content_size.width
        body = Text(justify='center')
        fits = glyphs_cover() and (width >= wordmark_width() or width <= 0)
        if fits:
            for line in wordmark_lines():
                body.append(line + '\n', style=f'bold {theme.color("accent")}')
        else:
            body.append(f'{WORDMARK.title()}\n', style=f'bold {theme.color("accent")}')
        body.append('\n')
        body.append(HINT, style=theme.color('fg_muted'))
        self.update(body)
