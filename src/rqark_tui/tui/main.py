from rich.cells import cell_len
from rich.segment import Segment
from rich.style import Style
from rich.text import Text

from textual import events
from textual.geometry import Offset
from textual.strip import Strip
from textual.widgets import RichLog

from rqark_tui.tui.clipboard import write_system_clipboard

#: Background colour used to paint the selected cells (macOS-dark-ish blue).
_SELECTION_BG = '#2E5E8C'

#: Sentinel column meaning "to the end of the line" (used for select-all).
_END_OF_LINE = 10**9


def _crop_plain(text: str, start_cell: int, end_cell: int) -> str:
    """Return the part of ``text`` covering cells ``[start_cell, end_cell)``."""
    if start_cell >= end_cell:
        return ''
    out: list[str] = []
    cells = 0
    for char in text:
        width = cell_len(char)
        if cells + width > end_cell:
            break
        if cells + width > start_cell:
            out.append(char)
        cells += width
    return ''.join(out)


def _apply_selection_style(strip: Strip, start: int, end: int) -> Strip:
    """Return a copy of ``strip`` with the selection background on cells ``[start, end)``."""
    selection_style = Style(bgcolor=_SELECTION_BG)
    segments: list[Segment] = []
    col = 0
    for segment in strip._segments:
        text, style, control = segment
        seg_len = 0 if control is not None else cell_len(text)
        seg_start, seg_end = col, col + seg_len
        overlap_start = max(seg_start, start)
        overlap_end = min(seg_end, end)
        if control is not None or seg_len == 0 or overlap_start >= overlap_end:
            segments.append(segment)
        else:
            selected = (style or Style()) + selection_style
            # Non-selected left part.
            if overlap_start > seg_start:
                left, segment = segment.split_cells(overlap_start - seg_start)
                segments.append(left)
            # Selected middle part (+ non-selected right part if any).
            if overlap_end < seg_end:
                mid, right = segment.split_cells(overlap_end - overlap_start)
                segments.append(
                    Segment(mid.text, (mid.style or Style()) + selection_style, mid.control)
                )
                segments.append(right)
            else:
                segments.append(
                    Segment(segment.text, selected, segment.control)
                )
        col = seg_end
    return Strip(segments, strip.cell_length)


class MessagePane(RichLog):
    """Scrollable message area showing the submitted messages.

    Supports normal copy-paste behaviour:

    - Drag with the mouse to select text (highlighted in blue).
    - ``Ctrl+C`` copies the selection to both the in-app clipboard and the
      OS clipboard (so it can be pasted into other applications).
    - ``Ctrl+A`` selects the whole log.
    """

    DEFAULT_CSS = """
    MessagePane {
        height: 1fr;
        border: round #303030;
        padding: 1 2;
        background: #141414;
    }
    MessagePane:focus {
        background-tint: transparent;
        border: round #303030;
    }
    """

    def __init__(self, **kwargs) -> None:
        # `wrap=True` + a small `min_width` so long messages wrap inside the
        # pane (no horizontal scrolling), which keeps them fully selectable
        # and copyable.
        super().__init__(wrap=True, min_width=1, **kwargs)
        self._message_count = 0
        # Per appended message: the row range it occupies in `self.lines` and
        # its original plain text. Used to reconstruct wrapped lines without
        # inserting artificial newlines when copying a whole message.
        self._message_spans: list[tuple[int, int]] = []
        self._message_texts: list[str] = []
        # Selection state in virtual coordinates: (row, col) where row is the
        # line index in `self.lines` and col is the cell column (scroll-aware).
        self._selection_start: tuple[int, int] | None = None
        self._selection_end: tuple[int, int] | None = None
        self._selection_anchor: tuple[int, int] | None = None

    # --- message appending -------------------------------------------------

    def append_message(self, text: str) -> None:
        """Append a submitted message to the pane.

        Each message header carries a clickable ``[copy]`` button (``@click``
        style meta) that copies the whole message — a VS Code-proof fallback
        that doesn't rely on Ctrl+C reaching the app.
        """
        self._message_count += 1
        message_index = self._message_count - 1
        content = Text()
        content.append('you ', Style(bold=True, color='#DC143C'))
        content.append(f'#{self._message_count}', Style(dim=True))
        content.append(
            ' [copy]',
            Style(color='#4FC1FF', meta={'@click': f'copy_message({message_index})'}),
        )
        content.append('\n')
        content.append(text)  # Plain text: brackets in user text stay literal.
        start = len(self.lines)
        self.write(content)
        end = len(self.lines)
        if end > start:
            self._message_spans.append((start, end))
            self._message_texts.append(f'you #{self._message_count}\n{text}')
        self.scroll_end(animate=False)

    def clear(self) -> 'MessagePane':
        """Clear the log and any active selection."""
        self._clear_selection()
        self._message_spans.clear()
        self._message_texts.clear()
        return super().clear()

    # --- whole-message copy button -------------------------------------------

    def action_copy_message(self, message_index: int) -> None:
        """Copy the whole message at ``message_index`` (invoked by the [copy] button)."""
        if 0 <= message_index < len(self._message_texts):
            self._copy_to_clipboards(self._message_texts[message_index])
            self._clear_selection()

    # --- selection helpers --------------------------------------------------

    @property
    def _has_selection(self) -> bool:
        return self._selection_start is not None and self._selection_end is not None

    def _clear_selection(self) -> None:
        self._selection_start = None
        self._selection_end = None
        self._selection_anchor = None
        self.refresh()

    def _virtual_offset(self, offset: Offset) -> tuple[int, int]:
        """Map a content-area offset to ``(row, col)`` in the log's virtual space."""
        scroll_x, scroll_y = self.scroll_offset
        row = min(max(scroll_y + offset.y, 0), max(len(self.lines) - 1, 0))
        col = max(scroll_x + offset.x, 0)
        return (row, col)

    def _span_for_row(self, row: int) -> int | None:
        """Return the index of the message whose rows contain ``row``, or ``None``."""
        for index, (start, end) in enumerate(self._message_spans):
            if start <= row < end:
                return index
        return None

    def _column_range(
        self,
        row: int,
        start: tuple[int, int],
        end: tuple[int, int],
    ) -> tuple[int, int]:
        """Return the selected column range ``(start, end)`` for ``row``.

        For a multi-row selection, the first and last rows are clipped at the
        drag endpoints and rows in between span the whole line.
        """
        if start[0] == end[0]:
            return start[1], end[1]
        if row == start[0]:
            return start[1], _END_OF_LINE
        if row == end[0]:
            return 0, end[1]
        return 0, _END_OF_LINE

    def _selection_text(self) -> str:
        """Return the plain text covered by the current selection.

        Whole messages (every row of a message selected) are copied from their
        original text, so wrapped lines are reconstructed exactly instead of
        being joined with artificial newlines.
        """
        if not self._has_selection:
            return ''
        start, end = self._selection_start, self._selection_end
        first_row = start[0]
        last_row = min(end[0], len(self.lines) - 1)
        if first_row > last_row:
            return ''
        selected: list[str] = []
        row = first_row
        while row <= last_row:
            span_index = self._span_for_row(row)
            if span_index is not None:
                span_start, span_end = self._message_spans[span_index]
                if span_start >= first_row and span_end - 1 <= last_row:
                    # Whole message selected: use the original (unwrapped) text.
                    selected.append(self._message_texts[span_index])
                    row = span_end
                    continue
            # Partial selection: crop this row's columns.
            text = self.lines[row].text if row < len(self.lines) else ''
            col_start, col_end = self._column_range(row, start, end)
            selected.append(_crop_plain(text, col_start, col_end))
            row += 1
        return '\n'.join(selected)

    def _copy_to_clipboards(self, text: str) -> None:
        """Copy to both the in-app clipboard (for Ctrl+V in the input) and the OS."""
        self.app.copy_to_clipboard(text)
        write_system_clipboard(text)
        self.notify('Copied')

    # --- mouse selection -----------------------------------------------------

    async def _on_mouse_down(self, event: events.MouseDown) -> None:
        if event.button == 1:  # left button
            self.focus()
            self.capture_mouse()
            offset = event.get_content_offset(self)
            if offset is not None:
                self._selection_anchor = self._selection_start = self._selection_end = self._virtual_offset(offset)
                self.refresh()
            else:
                # Click on border/padding: drop any existing selection.
                self._clear_selection()
        await super()._on_mouse_down(event)

    async def _on_mouse_move(self, event: events.MouseMove) -> None:
        if self._selection_anchor is not None and (event.button & 1):
            current = self._virtual_offset(event.get_content_offset_capture(self))
            anchor = self._selection_anchor
            if current < anchor:
                self._selection_start, self._selection_end = current, anchor
            else:
                self._selection_start, self._selection_end = anchor, current
            self.refresh()

    async def _on_mouse_up(self, event: events.MouseUp) -> None:
        if self._selection_anchor is not None:
            self.release_mouse()
            self._selection_anchor = None
            if not self._has_selection or self._selection_start == self._selection_end:
                self._clear_selection()
            else:
                self.refresh()
        await super()._on_mouse_up(event)

    # --- keyboard copy -------------------------------------------------------

    async def _on_key(self, event: events.Key) -> None:
        if event.key == 'ctrl+c' and self._has_selection:
            text = self._selection_text()
            if text:
                self._copy_to_clipboards(text)
                event.stop()
                event.prevent_default()
            return
        if event.key == 'ctrl+a':
            if self.lines:
                self._selection_start = (0, 0)
                self._selection_end = (len(self.lines) - 1, _END_OF_LINE)
                event.stop()
                event.prevent_default()
                self.refresh()
                return
        await super()._on_key(event)

    # --- selection rendering ---------------------------------------------------

    def render_line(self, y: int) -> Strip:
        """Render line ``y``, overlaying the selection highlight if needed."""
        strip = super().render_line(y)
        if not self._has_selection:
            return strip
        scroll_x, scroll_y = self.scroll_offset
        row = scroll_y + y
        if row >= len(self.lines):
            return strip
        start, end = self._selection_start, self._selection_end
        if not (start[0] <= row <= end[0]):
            return strip
        # Convert virtual columns to strip-local columns.
        sel_start, sel_end = self._column_range(row, start, end)
        local_start = max(sel_start - scroll_x, 0)
        local_end = min(sel_end - scroll_x, strip.cell_length)
        if local_start >= local_end:
            return strip
        return _apply_selection_style(strip, local_start, local_end)
