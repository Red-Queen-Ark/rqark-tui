"""The wordmark shown while the session on screen has nothing in it.

A brand-new session used to open onto an empty transcript, which reads as a
broken window rather than a fresh start. The splash fills that area with the
product name until the first message arrives.
"""

from rich.text import Text
from textual.widgets import Static

from rqark_tui.tui.theme import active_theme

GLYPH_ROWS = 10
GLYPH_COLUMNS = 5

LETTER_GAP = 1
WORD_GAP = 3

_GLYPHS: dict[str, tuple[str, ...]] = {
    'A': ('.###.', '#...#', '#...#', '#...#', '#####', '#...#', '#...#', '#...#', '#...#', '#...#'),
    'D': ('####.', '#...#', '#...#', '#...#', '#...#', '#...#', '#...#', '#...#', '#...#', '####.'),
    'E': ('#####', '#....', '#....', '#....', '####.', '#....', '#....', '#....', '#....', '#####'),
    'K': ('#...#', '#...#', '#..#.', '#.#..', '##...', '##...', '#.#..', '#..#.', '#...#', '#...#'),
    'N': ('#...#', '#...#', '##..#', '##..#', '#.#.#', '#.#.#', '#..##', '#..##', '#...#', '#...#'),
    'Q': ('.###.', '#...#', '#...#', '#...#', '#...#', '#...#', '#.#.#', '#..#.', '.###.', '...##'),
    'R': ('####.', '#...#', '#...#', '#...#', '####.', '#.#..', '#..#.', '#...#', '#...#', '#...#'),
    'U': ('#...#', '#...#', '#...#', '#...#', '#...#', '#...#', '#...#', '#...#', '#...#', '.###.'),
}

_HALF_BLOCKS = {('1', '1'): '█', ('1', '0'): '▀', ('0', '1'): '▄', ('0', '0'): ' '}

#: What the splash spells out.
WORDMARK = 'RED QUEEN ARK'

#: Hint under the wordmark.
HINT = 'Type a message to begin'


def _glyph(letter: str) -> tuple[str, ...]:
    """One letter as terminal rows, blanks for a letter the grid does not cover."""
    rows = GLYPH_ROWS // 2
    bitmap = _GLYPHS.get(letter)
    if bitmap is None:
        return (GLYPH_COLUMNS * ' ',) * rows
    return tuple(
        ''.join(
            _HALF_BLOCKS[('1' if top == '#' else '0', '1' if bottom == '#' else '0')]
            for top, bottom in zip(bitmap[row], bitmap[row + 1])
        )
        for row in range(0, GLYPH_ROWS, 2)
    )


def _placed(wordmark: str) -> list[tuple[tuple[str, ...], int]]:
    """Each glyph with the blank columns that come before it."""
    placed: list[tuple[tuple[str, ...], int]] = []
    gap = 0
    for letter in wordmark.strip():
        if letter == ' ':
            gap = WORD_GAP
            continue
        placed.append((_glyph(letter), gap))
        gap = LETTER_GAP
    return placed


def glyphs_cover(wordmark: str = WORDMARK) -> bool:
    """Whether every letter of the wordmark has a block glyph."""
    return all(letter in _GLYPHS for letter in wordmark if letter != ' ')


def wordmark_lines(wordmark: str = WORDMARK) -> list[str]:
    """The wordmark as block art, one string per row, all the same width."""
    placed = _placed(wordmark)
    rows = [
        ''.join(' ' * gap + glyph[row] for glyph, gap in placed).rstrip()
        for row in range(GLYPH_ROWS // 2)
    ]
    width = max(len(row) for row in rows)
    return [row.ljust(width) for row in rows]


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
