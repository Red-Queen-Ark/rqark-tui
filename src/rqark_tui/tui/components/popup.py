from collections.abc import Sequence

from rich.markup import escape
from textual.widgets import Static

MAX_VISIBLE = 6

Entry = tuple[str, str]


class PopupSelector(Static):
    """Transient overlay popup: a selectable list (selector) or read-only lines (display)."""

    DEFAULT_CSS = """
    PopupSelector {
        display: none;
        border: round #303030;
        background: #1a1a1a;
        padding: 0 2;
        height: auto;
        max-height: 10;
        color: #e0e0e0;
    }
    """

    def __init__(self, title: str = '') -> None:
        super().__init__('')
        self._default_title = title
        self._entries: list[Entry] = []
        self._selectable = True
        self._selected = 0
        self._scroll = 0

    @property
    def selectable(self) -> bool:
        """True when the popup is a selector; False in read-only display mode."""
        return self._selectable

    @property
    def selected_entry(self) -> Entry | None:
        """The highlighted (label, value) entry in selector mode, else None."""
        if not self._selectable or not self._entries:
            return None
        return self._entries[self._selected]

    @property
    def _visible_count(self) -> int:
        return min(len(self._entries), MAX_VISIBLE)

    def show(self, entries: Sequence[Entry], *, title: str | None = None, index: int = 0) -> None:
        """Open as a selector over ``entries``, highlighting ``index``."""
        self._entries = list(entries)
        self._selectable = True
        self._selected = max(0, min(index, len(self._entries) - 1))
        self._scroll = 0
        self._apply_title(title)
        self.display = bool(self._entries)
        self._update_counter()
        self.refresh()

    def show_text(self, text: str, *, title: str | None = None) -> None:
        """Open in read-only display mode; ``text`` renders one line per row."""
        lines = text.splitlines()
        if not lines:
            self.hide()
            return
        self._entries = [(line, '') for line in lines]
        self._selectable = False
        self._selected = 0
        self._scroll = 0
        self._apply_title(title)
        self.display = True
        self._update_counter()
        self.refresh()

    def hide(self) -> None:
        self._entries = []
        self._selectable = True
        self._selected = 0
        self._scroll = 0
        self.display = False
        self._update_counter()

    def move(self, delta: int) -> None:
        """Move the highlight (selector) or the scroll window (display)."""
        if not self._entries:
            return
        if self._selectable:
            self._selected = max(0, min(len(self._entries) - 1, self._selected + delta))
        else:
            self._scroll += delta
        self._adjust_scroll()
        self._update_counter()
        self.refresh()

    def _apply_title(self, title: str | None) -> None:
        self.border_title = self._default_title if title is None else title

    def _update_counter(self) -> None:
        total = len(self._entries)
        count = self._visible_count
        if total <= count:
            self.border_subtitle = ''
            return
        if self._selectable:
            self.border_subtitle = f'{self._selected + 1}/{total}'
        else:
            start = self._scroll + 1
            end = min(self._scroll + count, total)
            self.border_subtitle = f'{start}–{end}/{total}'

    def _adjust_scroll(self) -> None:
        count = self._visible_count
        if self._selectable:
            if self._selected < self._scroll:
                self._scroll = self._selected
            elif self._selected >= self._scroll + count:
                self._scroll = self._selected - count + 1
        self._scroll = max(0, min(self._scroll, max(0, len(self._entries) - count)))

    def render(self) -> str:
        if not self._entries:
            return ''
        count = self._visible_count
        lines: list[str] = []
        for i in range(count):
            index = self._scroll + i
            if index >= len(self._entries):
                break
            display, _value = self._entries[index]
            marker = '❯' if self._selectable and index == self._selected else ' '
            lines.append(f'{marker} {escape(display)}')
        return '\n'.join(lines)
