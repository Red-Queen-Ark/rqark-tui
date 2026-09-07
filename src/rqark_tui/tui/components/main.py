import json
from dataclasses import dataclass, field
from datetime import datetime

from rich.cells import cell_len
from rich.markdown import Markdown
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

_LABEL_COLORS = {
    'user': '#DC143C',
    'agent': '#A020F0',
    'tools': '#A020F0',
    'system': '#808080',
}

_ACCENT = '#4FC1FF'


@dataclass
class _Section:
    mode: str
    name: str
    text: str = ''
    collapsed: bool = False


@dataclass
class _Block:
    kind: str
    time: str
    sections: list[_Section] = field(default_factory=list)
    open: bool = True
    start: int = 0


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

    Each message gets a header row (``User`` / ``Agent`` / ``System``) with the
    timestamp and a ``[copy]`` button right-aligned, followed by the body.
    Reasoning and tool results render as collapsible accordions (expanded by
    default). Mouse selection / Ctrl+C / Ctrl+A copy behaviour is preserved.
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
        # Per appended message block: its row range in `self.lines` and the
        # plain text used by the whole-message [copy] button / selection.
        self._blocks: list[_Block] = []
        self._message_spans: list[tuple[int, int]] = []
        self._message_texts: list[str] = []
        # Selection state in virtual coordinates: (row, col) where row is the
        # line index in `self.lines` and col is the cell column (scroll-aware).
        self._selection_start: tuple[int, int] | None = None
        self._selection_end: tuple[int, int] | None = None
        self._selection_anchor: tuple[int, int] | None = None
        self._needs_initial_rebuild = True
        self._tool_keys: dict[str, str] = {}

    def set_tool_keys(self, tool_keys: dict[str, str]) -> None:
        self._tool_keys = tool_keys

    def on_resize(self, event) -> None:
        super().on_resize(event)
        if self._needs_initial_rebuild and self._size_known:
            self._needs_initial_rebuild = False
            if self._blocks:
                self._rebuild()

    # --- message appending -------------------------------------------------

    @staticmethod
    def _format_time(at: datetime | None) -> str:
        if at is None:
            at = datetime.now()
        if at.tzinfo is not None:
            at = at.astimezone()
        return at.strftime('%Y-%m-%d %H:%M:%S')

    def append_message(self, text: str, at: datetime | None = None) -> None:
        self._close_last()
        self._new_block('user', at, [('body', '', text)])
        self._rewrite_tail(len(self._blocks) - 1)

    def append_agent_delta(self, text: str, at: datetime | None = None) -> None:
        idx, block = self._open_agent(at)
        if not block.sections or block.sections[-1].mode != 'body':
            block.sections.append(_Section('body', '', ''))
        block.sections[-1].text += text
        self._rewrite_tail(idx)

    def append_think_delta(self, text: str, at: datetime | None = None) -> None:
        idx, block = self._open_agent(at)
        if block.sections and block.sections[0].mode == 'think':
            block.sections[0].text += text
        else:
            block.sections.insert(0, _Section('think', 'thinking', text, collapsed=True))
        self._rewrite_tail(idx)

    def close_agent_message(self) -> None:
        self._close_last()

    def append_tool_call(self, name: str, arguments: str = '', at: datetime | None = None) -> None:
        if self._blocks and self._blocks[-1].kind == 'tools' and self._blocks[-1].open:
            block = self._blocks[-1]
            idx = len(self._blocks) - 1
        else:
            self._close_last()
            self._new_block('tools', at, [])
            block = self._blocks[-1]
            idx = len(self._blocks) - 1
        block.sections.append(_Section('tool', name, arguments))
        self._rewrite_tail(idx)

    def append_tool_result(self, name: str, content: str, at: datetime | None = None) -> None:
        if self._blocks and self._blocks[-1].kind == 'tools':
            block = self._blocks[-1]
            block.open = True
            idx = len(self._blocks) - 1
        else:
            self._new_block('tools', at, [])
            block = self._blocks[-1]
            idx = len(self._blocks) - 1
        block.sections.append(_Section('result', name or 'tool', content.strip(), collapsed=True))
        self._rewrite_tail(idx)

    def append_error(self, text: str, at: datetime | None = None) -> None:
        self._close_last()
        self._new_block('system', at, [('error', '', text)])
        self._rewrite_tail(len(self._blocks) - 1)

    def append_system(self, text: str, at: datetime | None = None) -> None:
        self._close_last()
        self._new_block('system', at, [('sys', '', text)])
        self._rewrite_tail(len(self._blocks) - 1)

    # --- block bookkeeping --------------------------------------------------

    def _new_block(self, kind: str, at: datetime | None, sections: list[tuple[str, str, str]]) -> _Block:
        block = _Block(kind, self._format_time(at))
        for mode, name, text in sections:
            block.sections.append(_Section(mode, name, text))
        block.start = len(self.lines)
        self._blocks.append(block)
        return block

    def _close_last(self) -> None:
        if self._blocks and self._blocks[-1].open:
            self._blocks[-1].open = False

    def _last_agent(self) -> tuple[int, _Block] | None:
        if not self._blocks:
            return None
        block = self._blocks[-1]
        if not block.open or block.kind not in ('agent', 'tools'):
            return None
        if block.kind == 'tools':
            return None
        if any(s.mode == 'tool' for s in block.sections):
            return None
        return len(self._blocks) - 1, block

    def _open_agent(self, at: datetime | None) -> tuple[int, _Block]:
        last = self._last_agent()
        if last is not None:
            return last
        self._close_last()
        block = self._new_block('agent', at, [])
        return len(self._blocks) - 1, block

    def _rewrite_tail(self, idx: int) -> None:
        if not self._size_known:
            return
        block = self._blocks[idx]
        del self.lines[block.start:]
        self._line_cache.clear()
        del self._message_spans[idx:]
        del self._message_texts[idx:]
        self._emit_block(idx)
        self._clear_selection()

    def _rebuild(self) -> None:
        del self.lines[:]
        self._line_cache.clear()
        self._message_spans.clear()
        self._message_texts.clear()
        for idx in range(len(self._blocks)):
            block = self._blocks[idx]
            block.start = len(self.lines)
            self._emit_block(idx)
        self._clear_selection()

    def _emit_block(self, idx: int) -> None:
        block = self._blocks[idx]
        start = len(self.lines)
        width = max(self.scrollable_content_region.width, 40)
        self.write(self._header_row(block, idx), width=width, scroll_end=False)
        for si, section in enumerate(block.sections):
            row: object | None = None
            if section.mode == 'body':
                if section.text and block.kind == 'agent':
                    row = Markdown(section.text)
                elif section.text:
                    row = Text(section.text, style=Style(color='#ffffff'))
            elif section.mode == 'think':
                row = self._accordion_row(section, idx, si)
                if not section.collapsed and section.text:
                    self.write(Text(section.text, style=Style(dim=True, italic=True, color='#9a9a9a')), width=width, scroll_end=False)
            elif section.mode == 'tool':
                row = self._tool_row(section)
            elif section.mode == 'result':
                row = self._accordion_row(section, idx, si, prefix='tool result: ')
                if not section.collapsed and section.text:
                    self.write(Text(section.text, style=Style(dim=True, color='#9e9e9e')), width=width, scroll_end=False)
            elif section.mode == 'error':
                if section.text:
                    row = Text(section.text, style=Style(color='#DC143C'))
            elif section.text:
                row = Text(section.text, style=Style(dim=True, color='#c0c0c0'))
            if row is not None:
                self.write(row, width=width, scroll_end=False)
        end = len(self.lines)
        if end > start:
            self._message_spans.append((start, end))
            self._message_texts.append(self._copy_text(block))
        self.scroll_end(animate=False)

    def _header_row(self, block: _Block, idx: int) -> Text:
        label = 'Agent' if block.kind in ('agent', 'tools') else block.kind.title()
        head = Text()
        head.append(f'{label} ', Style(bold=True, color=_LABEL_COLORS.get(block.kind, '#808080')))
        dt = block.time
        head.append(' ' * self._pad_to(cell_len(label) + 1 + cell_len(dt) + len(' [copy]')))
        head.append(dt, Style(dim=True, color='#808080'))
        head.append(' [copy]', Style(color=_ACCENT, meta={'@click': f'copy_message({idx})'}))
        return head

    def _tool_display(self, section: _Section) -> str:
        key = self._tool_keys.get(section.name)
        if key:
            try:
                data = json.loads(section.text or '{}')
            except ValueError:
                data = {}
            if isinstance(data, dict) and data.get(key) is not None:
                return str(data[key])
        return section.text[:40] if section.text else ''

    def _copy_text(self, block: _Block) -> str:
        label = 'Agent' if block.kind in ('agent', 'tools') else block.kind.title()
        parts = [label]
        for section in block.sections:
            if section.mode == 'tool':
                display = self._tool_display(section)
                parts.append(f'use tool {section.name}' + (f' {display}' if display else ''))
            elif section.text:
                parts.append(section.text)
        return '\n'.join(parts)

    def _pad_to(self, width: int) -> int:
        content = self.scrollable_content_region.width
        if content < 10:
            return max(width - 1, 0)
        return max(content - width, 0)

    def _tool_row(self, section: _Section) -> Text:
        row = Text()
        row.append('use tool ', Style(color='#c8a000'))
        row.append(section.name, Style(bold=True, color='#FFD700'))
        display = self._tool_display(section)
        if display:
            row.append(f' {display}', Style(dim=True, color='#8a6d00'))
        return row

    def _accordion_row(self, section: _Section, idx: int, si: int, prefix: str = '') -> Text:
        marker = '▶' if section.collapsed else '▼'
        row = Text()
        row.append(f'{marker} {prefix}{section.name}', Style(dim=True, color='#808080', meta={'@click': f'toggle_section({idx},{si})'}))
        return row

    def action_copy_message(self, message_index: int) -> None:
        """Copy the whole message at ``message_index`` (invoked by the [copy] button)."""
        if 0 <= message_index < len(self._message_texts):
            self._copy_to_clipboards(self._message_texts[message_index])
            self._clear_selection()

    def action_toggle_section(self, block_index: int, section_index: int) -> None:
        """Expand/collapse an accordion section (thinking / tool result)."""
        if 0 <= block_index < len(self._blocks):
            block = self._blocks[block_index]
            if 0 <= section_index < len(block.sections):
                section = block.sections[section_index]
                section.collapsed = not section.collapsed
                if block_index == len(self._blocks) - 1:
                    self._rewrite_tail(block_index)
                else:
                    self._rebuild()

    def clear(self) -> 'MessagePane':
        """Clear the log and any active selection."""
        self._blocks.clear()
        self._message_spans.clear()
        self._message_texts.clear()
        self._clear_selection()
        return super().clear()

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
        if start is None or end is None:
            return ''
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
        start, end = self._selection_start, self._selection_end
        if start is None or end is None:
            return strip
        scroll_x, scroll_y = self.scroll_offset
        row = scroll_y + y
        if row >= len(self.lines):
            return strip
        if not (start[0] <= row <= end[0]):
            return strip
        # Convert virtual columns to strip-local columns.
        sel_start, sel_end = self._column_range(row, start, end)
        local_start = max(sel_start - scroll_x, 0)
        local_end = min(sel_end - scroll_x, strip.cell_length)
        if local_start >= local_end:
            return strip
        return _apply_selection_style(strip, local_start, local_end)
