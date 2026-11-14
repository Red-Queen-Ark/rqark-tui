import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from rich.cells import cell_len
from rich.console import RenderableType
from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual import events
from textual.geometry import Offset, Size
from textual.message import Message
from textual.strip import Strip
from textual.timer import Timer
from textual.widgets import RichLog

from rqark_tui.tui import diff
from rqark_tui.tui.clipboard import write_system_clipboard
from rqark_tui.tui.syntax import markdown

#: Background colour used to paint the selected cells (macOS-dark-ish blue).
_SELECTION_BG = '#2E5E8C'

#: Sentinel column meaning "to the end of the line" (used for select-all).
_END_OF_LINE = 10**9

_LABEL_COLORS = {'user': '#DC143C', 'agent': '#A020F0', 'tools': '#A020F0', 'system': '#808080', 'status': '#4FC1FF'}

_ACCENT = '#4FC1FF'

#: Colour of the ``[revert]`` button on user messages.
_REVERT = '#FFA500'

#: Characters of a subagent id kept in the header label.
_AGENT_ID_PREFIX = 8


def _agent_label(agent_id: str, path: tuple[str, ...]) -> str:
    """Name the agent behind an event: agent name for the main agent, short id for a subagent."""
    if not agent_id:
        return ''
    if path:
        return agent_id[:_AGENT_ID_PREFIX]
    return agent_id.partition(':')[0]


def _content_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list | tuple):
        return '\n'.join(part for part in (_content_text(item) for item in value) if part)
    if isinstance(value, dict):
        text = value.get('text')
        return _content_text(text) if text is not None else ''
    if value is None:
        return ''
    return str(value)


@dataclass
class _Section:
    mode: str
    name: str
    text: str = ''
    collapsed: bool = False
    rendered: tuple[int, str, list[Strip]] | None = field(default=None, compare=False, repr=False)
    display: str | None = field(default=None, compare=False, repr=False)
    diff: bool = False

    def __post_init__(self) -> None:
        self.text = _content_text(self.text)


@dataclass
class _Block:
    kind: str
    time: str
    agent: str = ''
    sections: list[_Section] = field(default_factory=list)
    open: bool = True
    start: int = 0
    message_id: str = ''


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
                segments.append(Segment(mid.text, (mid.style or Style()) + selection_style, mid.control))
                segments.append(right)
            else:
                segments.append(Segment(segment.text, selected, segment.control))
        col = seg_end
    return Strip(segments, strip.cell_length)


class _Rendered:
    """Strips already rendered at one width, appended to the log without re-rendering."""

    __slots__ = ('strips',)

    def __init__(self, strips: list[Strip]) -> None:
        self.strips = strips


class MessagePane(RichLog):
    """Scrollable message area showing the submitted messages.

    Each message gets a header row (``User`` / ``Agent <name>`` / ``System``)
    with the timestamp and a ``[copy]`` button right-aligned, followed by the
    body. User messages also carry a ``[revert]`` button just left of ``[copy]``
    (once more than one user turn exists), which asks the app to drop that user
    message and everything after it. Agent blocks are labelled with the emitting
    agent (the agent name for the main agent, a short id for a subagent) so both
    are told apart. Reasoning and tool results render as collapsible accordions
    (expanded by default). Mouse selection / Ctrl+C / Ctrl+A copy behaviour is
    preserved.

    Streaming deltas only mutate the block model; the widget re-renders at most
    once per ``FLUSH_INTERVAL_SECONDS`` (see :meth:`_mark_dirty`), so a long
    stream costs O(text) renders instead of one full re-render per token.

    Only a window of the transcript is mounted in ``self.lines``: the newest
    ``TRANSCRIPT_MAX_ROWS`` rows. Blocks above the window live in ``_blocks``
    only and are rendered again when the reader scrolls to the top, so the cost
    of an append, a flush or a resize stays bounded by the window instead of
    growing with the session.
    """

    FLUSH_INTERVAL_SECONDS = 0.2

    #: Rows of transcript kept mounted. A block's height is only known once it
    #: is rendered, so the window is trimmed and refilled block by block.
    TRANSCRIPT_MAX_ROWS = 300

    #: Rows added above the window each time the reader reaches its top.
    TRANSCRIPT_BACKFILL_ROWS = 150

    #: Quiet time after the last resize event before the transcript is re-wrapped.
    #: A drag delivers a resize every cell, and re-wrapping the whole log on each
    #: of them blocks the message loop for the length of the drag.
    RESIZE_DEBOUNCE_SECONDS = 0.15

    DEFAULT_CSS = """
    MessagePane {
        height: 1fr;
        border: round #303030;
        padding: 1 2;
        overflow-x: hidden;
        background: #141414;
    }
    MessagePane:focus {
        background-tint: transparent;
        border: round #303030;
    }
    """

    class RevertRequested(Message):
        """Posted when a message's ``[revert]`` button is clicked."""

        def __init__(self, pane: 'MessagePane', message_id: str) -> None:
            super().__init__()
            self.pane = pane
            self.message_id = message_id

        @property
        def control(self) -> 'MessagePane':
            return self.pane

    def __init__(self, **kwargs) -> None:
        # `wrap=True` + a small `min_width` so long messages wrap inside the
        # pane (no horizontal scrolling), which keeps them fully selectable
        # and copyable.
        super().__init__(wrap=True, min_width=1, **kwargs)
        # Per appended message block: its row range in `self.lines`, or `None`
        # when the block sits above the mounted window.
        self._blocks: list[_Block] = []
        self._message_spans: list[tuple[int, int] | None] = []
        # Index of the first block rendered into `self.lines`. Blocks before it
        # only exist in the model and are re-rendered on demand.
        self._mount_start = 0
        self._mounted = False
        self._backfilling = False
        self._agent_index: dict[str, int] = {}
        self._status_index: int | None = None
        # Selection state in virtual coordinates: (row, col) where row is the
        # line index in `self.lines` and col is the cell column (scroll-aware).
        self._selection_start: tuple[int, int] | None = None
        self._selection_end: tuple[int, int] | None = None
        self._selection_anchor: tuple[int, int] | None = None
        self._mouse_captured = False
        self._wrap_width = 0
        self._tool_keys: dict[str, str] = {}
        self._dirty_index: int | None = None
        self._flush_timer: Timer | None = None
        self._resize_timer: Timer | None = None
        # The single transient status block (a running command's progress), if any.
        self._status: _Block | None = None

    def set_tool_keys(self, tool_keys: dict[str, str]) -> None:
        self._tool_keys = tool_keys
        for block in self._blocks:
            for section in block.sections:
                section.display = None

    def on_mount(self) -> None:
        self._flush_timer = self.set_interval(self.FLUSH_INTERVAL_SECONDS, self._flush_now)

    def on_unmount(self) -> None:
        if self._flush_timer is not None:
            self._flush_timer.stop()
            self._flush_timer = None
        if self._resize_timer is not None:
            self._resize_timer.stop()
            self._resize_timer = None
        self._dirty_index = None
        if self._mouse_captured:
            self._mouse_captured = False
            self.release_mouse()

    def on_resize(self, event) -> None:
        super().on_resize(event)
        if not self._size_known or not self._blocks:
            return
        if self.scrollable_content_region.width == self._wrap_width:
            return
        if self._wrap_width == 0:
            # First layout: nothing is on screen yet, so paint it now.
            self._rebuild()
            return
        # Re-wrap once the user stops dragging, not on every intermediate width:
        # each re-wrap re-parses every block, which a drag would chain back to back.
        if self._resize_timer is not None:
            self._resize_timer.stop()
        self._resize_timer = self.set_timer(self.RESIZE_DEBOUNCE_SECONDS, self._rewrap)

    def _rewrap(self) -> None:
        """Rebuild the transcript after a resize settles, if the width really changed."""
        self._resize_timer = None
        if not self._size_known or not self._blocks:
            return
        if self.scrollable_content_region.width != self._wrap_width:
            self._rebuild()

    # --- message appending -------------------------------------------------

    @staticmethod
    def _format_time(at: datetime | None) -> str:
        if at is None:
            at = datetime.now()
        if at.tzinfo is not None:
            at = at.astimezone()
        return at.strftime('%Y-%m-%d %H:%M:%S')

    def append_message(self, text: str, at: datetime | None = None, images: Sequence[str] | None = None, message_id: str = '') -> None:
        self._flush_now()
        self._close_last()
        sections: list[tuple[str, str, str]] = []
        if text:
            sections.append(('body', '', text))
        for index in range(len(images) if images is not None else 0):
            sections.append(('image', '', f'[image {index + 1}]'))
        self._new_block('user', at, sections, message_id=message_id)
        self._rewrite_tail(len(self._blocks) - 1)

    def set_last_user_message_id(self, message_id: str) -> None:
        """Attach the app-assigned id to the newest user block, making it revertible."""
        for index in range(len(self._blocks) - 1, -1, -1):
            block = self._blocks[index]
            if block.kind != 'user':
                continue
            if block.message_id == message_id:
                return
            block.message_id = message_id
            self._rewrite_tail(index)
            return

    def append_agent_delta(self, text: str, at: datetime | None = None, agent_id: str = '', path: tuple[str, ...] = ()) -> None:
        idx, block = self._open_agent(at, agent_id, path)
        if not block.sections or block.sections[-1].mode != 'body':
            block.sections.append(_Section('body', '', ''))
        block.sections[-1].text += _content_text(text)
        self._mark_dirty(idx)

    def append_think_delta(self, text: str, at: datetime | None = None, agent_id: str = '', path: tuple[str, ...] = ()) -> None:
        idx, block = self._open_agent(at, agent_id, path)
        if block.sections and block.sections[0].mode == 'think':
            block.sections[0].text += _content_text(text)
        else:
            block.sections.insert(0, _Section('think', 'thinking', text, collapsed=True))
        self._mark_dirty(idx)

    def close_agent_message(self, agent_id: str = '', path: tuple[str, ...] = ()) -> None:
        self._close_agent(_agent_label(agent_id, path))
        self._flush_now()

    def append_tool_call(self, name: str, arguments: str = '', at: datetime | None = None, agent_id: str = '', path: tuple[str, ...] = ()) -> None:
        self._flush_now()
        agent = _agent_label(agent_id, path)
        if self._blocks and self._blocks[-1].kind == 'tools' and self._blocks[-1].open and self._blocks[-1].agent == agent:
            block = self._blocks[-1]
            idx = len(self._blocks) - 1
        else:
            self._close_agent(agent)
            self._new_block('tools', at, [], agent)
            block = self._blocks[-1]
            idx = len(self._blocks) - 1
        block.sections.append(_Section('tool', name, arguments))
        self._append_section_rows(idx)

    def append_tool_result(self, name: str, content: str, at: datetime | None = None, agent_id: str = '', path: tuple[str, ...] = ()) -> None:
        self._flush_now()
        agent = _agent_label(agent_id, path)
        if self._blocks and self._blocks[-1].kind == 'tools' and self._blocks[-1].agent == agent:
            block = self._blocks[-1]
            block.open = True
            idx = len(self._blocks) - 1
        else:
            self._close_agent(agent)
            self._new_block('tools', at, [], agent)
            block = self._blocks[-1]
            idx = len(self._blocks) - 1
        block.sections.append(_Section('result', name or 'tool', content.strip(), collapsed=True, diff=diff.looks_like_diff(content)))
        self._append_section_rows(idx)

    def append_error(self, text: str, at: datetime | None = None) -> None:
        self._flush_now()
        self._close_last()
        self._new_block('system', at, [('error', '', text)])
        self._rewrite_tail(len(self._blocks) - 1)

    def append_system(self, text: str, at: datetime | None = None) -> None:
        self._flush_now()
        self._close_last()
        self._new_block('system', at, [('sys', '', text)])
        self._rewrite_tail(len(self._blocks) - 1)

    def show_status(self, text: str) -> None:
        """Show a transient status line as the newest block, updating it in place.

        A status line reports progress (``Compacting…``) rather than a message, so it
        never accumulates: re-showing rewrites the same block and
        :meth:`hide_status` takes it back off the transcript.
        """
        index = self._status_index
        if self._status is not None and index is not None and index < len(self._blocks) and self._blocks[index] is self._status:
            self._status.sections[0].text = _content_text(text)
            self._rewrite_tail(index)
            return
        self._flush_now()
        self._close_last()
        self._status = self._new_block('status', None, [('status', '', text)])
        self._status_index = len(self._blocks) - 1
        self._rewrite_tail(len(self._blocks) - 1)

    def hide_status(self) -> None:
        """Drop the transient status line, re-rendering the transcript without it."""
        index = self._status_index
        status, self._status = self._status, None
        self._status_index = None
        if status is None or index is None or index >= len(self._blocks) or self._blocks[index] is not status:
            return
        self._flush_now()
        self._blocks.remove(status)
        self._truncate_tail(status.start, index)

    # --- block bookkeeping --------------------------------------------------

    def _new_block(self, kind: str, at: datetime | None, sections: list[tuple[str, str, str]], agent: str = '', message_id: str = '') -> _Block:
        block = _Block(kind, self._format_time(at), agent, message_id=message_id)
        for mode, name, text in sections:
            block.sections.append(_Section(mode, name, text))
        block.start = len(self.lines)
        self._blocks.append(block)
        self._message_spans.append(None)
        if kind == 'agent':
            self._agent_index[agent] = len(self._blocks) - 1
        return block

    def _close_last(self) -> None:
        if self._blocks and self._blocks[-1].open:
            self._blocks[-1].open = False

    def _close_agent(self, agent: str) -> None:
        """Close ``agent``'s open text block, wherever it sits in the log."""
        index = self._agent_index.pop(agent, None)
        if index is not None and index < len(self._blocks):
            block = self._blocks[index]
            if block.kind == 'agent' and block.agent == agent and block.open:
                block.open = False
                return
        for block in reversed(self._blocks):
            if block.open and block.kind == 'agent' and block.agent == agent:
                block.open = False
                return

    def _last_agent(self, agent: str) -> tuple[int, _Block] | None:
        """The newest open text block of ``agent``; concurrent agents each keep their own."""
        index = self._agent_index.get(agent)
        if index is not None and index < len(self._blocks):
            block = self._blocks[index]
            if block.kind == 'agent' and block.agent == agent:
                if not block.open or any(s.mode == 'tool' for s in block.sections):
                    return None
                return index, block
        for index in range(len(self._blocks) - 1, -1, -1):
            block = self._blocks[index]
            if block.kind != 'agent' or block.agent != agent:
                continue
            self._agent_index[agent] = index
            if not block.open or any(s.mode == 'tool' for s in block.sections):
                return None
            return index, block
        return None

    def _open_agent(self, at: datetime | None, agent_id: str = '', path: tuple[str, ...] = ()) -> tuple[int, _Block]:
        agent = _agent_label(agent_id, path)
        last = self._last_agent(agent)
        if last is not None:
            return last
        self._flush_now()
        block = self._new_block('agent', at, [], agent)
        return len(self._blocks) - 1, block

    def _mark_dirty(self, index: int) -> None:
        """Queue a re-render of ``index`` for the next flush tick (never blocks the loop)."""
        if self._dirty_index is None or index < self._dirty_index:
            self._dirty_index = index

    def _flush_now(self) -> None:
        """Render the queued block immediately; structural edits must not wait for a tick."""
        index = self._dirty_index
        if index is not None:
            self._rewrite_tail(index)

    def _pinned_to_tail(self) -> bool:
        """Whether the newest line is on screen, so appends may scroll back down.

        Asked *before* the transcript is touched: a user who scrolled up (wheel,
        scrollbar, keyboard) keeps reading the same rows while the log grows, and
        is only pulled back to the tail once they scroll down to it themselves.
        """
        return self.scroll_offset.y >= self.max_scroll_y

    def _rewrite_tail(self, idx: int) -> None:
        if not self._size_known:
            return
        if idx < self._mount_start:
            self._dirty_index = None
            return
        self._truncate_tail(self._blocks[idx].start, idx)

    def _truncate_tail(self, start: int, idx: int) -> None:
        if idx < self._mount_start:
            self._dirty_index = None
            return
        pinned = self._pinned_to_tail()
        self._dirty_index = None
        del self.lines[start:]
        self._line_cache.clear()
        self._widest_line_width = max((line.cell_length for line in self.lines), default=0)
        del self._message_spans[idx:]
        for index in range(idx, len(self._blocks)):
            self._blocks[index].start = len(self.lines)
            self._emit_block(index)
        if pinned:
            self.scroll_end(animate=False, immediate=True)
        self._clear_selection()
        self._trim_top(pinned)

    def _rebuild(self) -> None:
        """Re-render the mounted window at the current width."""
        pinned = self._pinned_to_tail()
        self._dirty_index = None
        if not self._mounted:
            self._mounted = True
            self._mount_start = self._tail_start()
        self._rewindow(pinned)

    def _tail_start(self) -> int:
        """Index of the oldest block that fits in the row budget, counting from the newest."""
        width = max(self.scrollable_content_region.width, 1)
        start = len(self._blocks)
        rows = 0
        while start > 0 and rows < self.TRANSCRIPT_MAX_ROWS:
            start -= 1
            rows += len(self._block_strips(start, width))
        return start

    def _rewindow(self, pinned: bool) -> None:
        """Render blocks from ``_mount_start`` downwards into ``self.lines``."""
        width = max(self.scrollable_content_region.width, 1)
        self._wrap_width = width
        del self.lines[:]
        self._line_cache.clear()
        self._widest_line_width = 0
        self._message_spans[:] = [None] * len(self._blocks)
        for index in range(self._mount_start, len(self._blocks)):
            self._blocks[index].start = len(self.lines)
            self._emit_block(index)
        self.virtual_size = Size(self._widest_line_width, len(self.lines))
        if pinned:
            self.scroll_end(animate=False, immediate=True)
        self._clear_selection()

    def _set_span(self, idx: int, span: tuple[int, int]) -> None:
        while len(self._message_spans) <= idx:
            self._message_spans.append(None)
        self._message_spans[idx] = span

    def _trim_top(self, pinned: bool) -> None:
        """Drop the oldest mounted blocks once the window outgrows its row budget.

        ``pinned`` is whether the view sat at the tail before the append that
        brought the window over budget. Rows the reader can see are never
        dropped: a scrolled-up view stops the trim at the top of its viewport,
        so the text under it stays put.
        """
        if len(self.lines) <= self.TRANSCRIPT_MAX_ROWS:
            return
        floor = len(self.lines) if pinned else int(self.scroll_offset.y)
        start = self._mount_start
        dropped = 0
        while start < len(self._blocks) - 1 and len(self.lines) - dropped > self.TRANSCRIPT_MAX_ROWS:
            span = self._message_spans[start]
            height = (span[1] - span[0]) if span is not None else 0
            if dropped + height > floor:
                break
            dropped += height
            self._message_spans[start] = None
            self._blocks[start].start = -1
            start += 1
        if start == self._mount_start or dropped <= 0:
            return
        self._mount_start = start
        del self.lines[:dropped]
        for index in range(start, len(self._blocks)):
            if self._blocks[index].start >= 0:
                self._blocks[index].start -= dropped
            span = self._message_spans[index]
            if span is not None:
                self._message_spans[index] = (span[0] - dropped, span[1] - dropped)
        self._line_cache.clear()
        self._widest_line_width = max((line.cell_length for line in self.lines), default=0)
        self.virtual_size = Size(self._widest_line_width, len(self.lines))
        if pinned:
            self.scroll_end(animate=False, immediate=True)
        else:
            self.scroll_to(y=max(self.scroll_offset.y - dropped, 0), animate=False)
        self._clear_selection()

    def _backfill(self) -> None:
        """Prepend older blocks above the window, keeping the read position fixed."""
        if self._backfilling or self._mount_start == 0 or not self._size_known:
            return
        self._backfilling = True
        try:
            width = max(self.scrollable_content_region.width, 1)
            start = self._mount_start
            rows = 0
            while start > 0 and rows < self.TRANSCRIPT_BACKFILL_ROWS:
                start -= 1
                rows += len(self._block_strips(start, width))
            strips: list[Strip] = []
            spans: list[tuple[int, int]] = []
            for index in range(start, self._mount_start):
                begin = len(strips)
                strips.extend(self._block_strips(index, width))
                spans.append((begin, len(strips)))
            added = len(strips)
            if not added:
                self._mount_start = start
                return
            self.lines[0:0] = strips
            for offset, index in enumerate(range(start, self._mount_start)):
                self._blocks[index].start = spans[offset][0]
                self._message_spans[index] = spans[offset]
            for index in range(self._mount_start, len(self._blocks)):
                if self._blocks[index].start >= 0:
                    self._blocks[index].start += added
                span = self._message_spans[index]
                if span is not None:
                    self._message_spans[index] = (span[0] + added, span[1] + added)
            self._mount_start = start
            self._line_cache.clear()
            self.virtual_size = Size(self._widest_line_width, len(self.lines))
            self.scroll_to(y=self.scroll_offset.y + added, animate=False)
        finally:
            self._backfilling = False

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        """Load earlier history when the reader reaches the top of the window."""
        super().watch_scroll_y(old_value, new_value)
        if new_value <= 0:
            self._backfill()

    @staticmethod
    def _stable_head(text: str) -> str:
        """The part of a streaming body that no later chunk can change.

        A body is only ever appended to, so everything up to the last blank line is
        fixed and the paragraph after it is still growing. A blank line inside an
        open code fence does not end a block, so such a split is walked back.
        """
        cut = text.rfind('\n\n')
        while cut > 0:
            head = text[: cut + 2]
            if head.count('```') % 2 == 0:
                return head
            cut = text.rfind('\n\n', 0, cut)
        return ''

    @staticmethod
    def _join_strips(base: list[Strip], extra: list[Strip], width: int) -> list[Strip]:
        """Join two rendered chunks with exactly one blank line between them.

        Each chunk is rendered on its own, so its outer blank lines are dropped and a
        single separator is inserted instead; joining them as-is would stack whatever
        spacing the renderer happened to leave at the seam.
        """
        while base and not base[-1].text.strip():
            base.pop()
        start = 0
        while start < len(extra) and not extra[start].text.strip():
            start += 1
        extra = extra[start:]
        if base and extra:
            base.append(Strip.blank(width))
        base.extend(extra)
        return base

    def _body_strips(self, section: _Section, width: int) -> list[Strip]:
        """Render an agent body as cached finished blocks plus the paragraph still streaming.

        Rendering every flush costs O(length) per tick, so a long answer would spend
        more time in the renderer than streaming. Everything before the last completed
        block is rendered to strips once per width and kept; each flush only renders
        what is new since the previous one, plus the tail.
        """
        text = section.text
        head = self._stable_head(text)
        cached = section.rendered
        if head:
            if cached is not None and cached[0] == width and head.startswith(cached[1]):
                base = list(cached[2])
                addition = head[len(cached[1]) :]
                if addition.strip():
                    self._join_strips(base, self._render_strips(markdown(addition), width), width)
            else:
                base = self._render_strips(markdown(head), width)
            section.rendered = (width, head, base)
            strips = list(base)
        else:
            section.rendered = None
            strips = []
        tail = text[len(head) :]
        if tail.strip():
            self._join_strips(strips, self._render_strips(markdown(tail), width), width)
        return strips

    def _render_strips(self, renderable: RenderableType, width: int) -> list[Strip]:
        """Render ``renderable`` to strips padded to ``width``, as ``RichLog.write`` does."""
        options = self.app.console.options.update_width(width)
        lines = list(Segment.split_lines(self.app.console.render(renderable, options)))
        if not lines:
            return [Strip.blank(width)]
        strips = Strip.from_lines(lines)
        for strip in strips:
            strip.adjust_cell_length(width)
        return strips

    def _write_strips(self, strips: list[Strip]) -> None:
        """Append pre-rendered strips to the log, skipping the render ``write`` would do."""
        self.lines.extend(strips)
        self._widest_line_width = max(self._widest_line_width, max((strip.cell_length for strip in strips), default=0))
        self.virtual_size = Size(self._widest_line_width, len(self.lines))

    def _block_strips(self, idx: int, width: int) -> list[Strip]:
        """Render block ``idx`` to strips at ``width``, without touching ``self.lines``."""
        block = self._blocks[idx]
        strips: list[Strip] = []
        self._collect_strips(self._header_row(block, idx), width, strips)
        for si in range(len(block.sections)):
            for row in self._section_rows(block, idx, si, width):
                self._collect_strips(row, width, strips)
        return strips

    def _collect_strips(self, row: RenderableType | _Rendered, width: int, strips: list[Strip]) -> None:
        if isinstance(row, _Rendered):
            strips.extend(row.strips)
        else:
            strips.extend(self._render_strips(row, width))

    def _emit_block(self, idx: int) -> None:
        block = self._blocks[idx]
        start = len(self.lines)
        width = max(self.scrollable_content_region.width, 1)
        self._wrap_width = width
        self._write_strips(self._block_strips(idx, width))
        block.start = start
        self._set_span(idx, (start, len(self.lines)))

    def _append_section_rows(self, idx: int) -> None:
        block = self._blocks[idx]
        span = (block.start, len(self.lines))
        if not self._size_known or idx != len(self._blocks) - 1 or not self._message_spans or self._message_spans[-1] != span:
            self._rewrite_tail(idx)
            return
        pinned = self._pinned_to_tail()
        width = max(self.scrollable_content_region.width, 1)
        self._wrap_width = width
        si = len(block.sections) - 1
        self._emit_rows(self._section_rows(block, idx, si, width), width)
        self._set_span(idx, (block.start, len(self.lines)))
        if pinned:
            self.scroll_end(animate=False, immediate=True)
        self._clear_selection()
        self._trim_top(pinned)

    def _section_rows(self, block: _Block, idx: int, si: int, width: int) -> list[RenderableType | _Rendered]:
        section = block.sections[si]
        rows: list[RenderableType | _Rendered] = []
        if section.mode == 'body':
            if section.text and block.kind == 'agent':
                if self._size_known:
                    rows.append(_Rendered(self._body_strips(section, width)))
                else:
                    rows.append(markdown(section.text))
            elif section.text:
                rows.append(Text(section.text, style=Style(color='#ffffff')))
        elif section.mode == 'image':
            rows.append(Text(section.text, style=Style(color=_ACCENT)))
        elif section.mode == 'think':
            rows.append(self._accordion_row(section, idx, si))
            if not section.collapsed and section.text:
                rows.append(Text(section.text, style=Style(dim=True, italic=True, color='#9a9a9a')))
        elif section.mode == 'tool':
            rows.append(self._tool_row(section))
        elif section.mode == 'result':
            rows.append(self._accordion_row(section, idx, si, prefix='tool result: '))
            if not section.collapsed and section.text:
                if section.diff:
                    rows.append(diff.render(section.text))
                else:
                    rows.append(Text(section.text, style=Style(dim=True, color='#9e9e9e')))
        elif section.mode == 'error':
            if section.text:
                rows.append(Text(section.text, style=Style(color='#DC143C')))
        elif section.mode == 'status':
            if section.text:
                rows.append(Text(section.text, style=Style(color=_ACCENT, italic=True)))
        elif section.text:
            rows.append(Text(section.text, style=Style(dim=True, color='#c0c0c0')))
        return rows

    def _emit_rows(self, rows: list[RenderableType | _Rendered], width: int) -> None:
        for row in rows:
            if isinstance(row, _Rendered):
                self._write_strips(row.strips)
            else:
                self.write(row, width=width, scroll_end=False)

    def _header_row(self, block: _Block, idx: int) -> Text:
        label = self._block_label(block)
        head = Text()
        head.append(f'{label} ', Style(bold=True, color=_LABEL_COLORS.get(block.kind, '#808080')))
        dt = block.time
        revert = self._revertible(block)
        tail = cell_len(dt) + len(' [copy]') + (len(' [revert]') if revert else 0)
        head.append(' ' * self._pad_to(cell_len(label) + 1 + tail))
        head.append(dt, Style(dim=True, color='#808080'))
        if revert:
            head.append(' [revert]', Style(color=_REVERT, meta={'@click': f'revert_message({idx})'}))
        head.append(' [copy]', Style(color=_ACCENT, meta={'@click': f'copy_message({idx})'}))
        width = max(self.scrollable_content_region.width, 1)
        if head.cell_len > width:
            head.right_crop(len(head.plain) - len(_crop_plain(head.plain, 0, width)))
        return head

    def _revertible(self, block: _Block) -> bool:
        """True when ``block`` is a revertible user message.

        The app can only drop from a user message downwards, and refuses when it
        is the session's only one — so the button only appears once a second user
        turn exists and the app has handed the block its message id.
        """
        if block.kind != 'user' or not block.message_id:
            return False
        return sum(1 for other in self._blocks if other.kind == 'user') > 1

    @staticmethod
    def _block_label(block: _Block) -> str:
        if block.kind not in ('agent', 'tools'):
            return block.kind.title()
        if not block.agent:
            return 'Agent'
        return f'Agent - {block.agent}'

    def _tool_display(self, section: _Section) -> str:
        if section.display is None:
            display: str | None = None
            key = self._tool_keys.get(section.name)
            if key:
                try:
                    data = json.loads(section.text or '{}')
                except ValueError:
                    data = {}
                if isinstance(data, dict) and data.get(key) is not None:
                    display = str(data[key])
            section.display = display if display is not None else (section.text[:40] if section.text else '')
        return section.display

    def _section_copy(self, section: _Section) -> str:
        if section.mode == 'tool':
            display = self._tool_display(section)
            return f'use tool {section.name}' + (f' {display}' if display else '')
        return section.text

    def _copy_text(self, block: _Block) -> str:
        parts = [self._block_label(block)]
        for section in block.sections:
            text = self._section_copy(section)
            if text:
                parts.append(text)
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
        row.append(f'{marker} {prefix}{section.name}', Style(bold=True, color='#757575', meta={'@click': f'toggle_section({idx},{si})'}))
        return row

    def action_copy_message(self, message_index: int) -> None:
        """Copy the whole message at ``message_index`` (invoked by the [copy] button)."""
        if 0 <= message_index < len(self._blocks):
            self._copy_to_clipboards(self._copy_text(self._blocks[message_index]))
            self._clear_selection()

    def action_revert_message(self, message_index: int) -> None:
        """Ask to revert the session to the user message at ``message_index`` (the [revert] button)."""
        if not (0 <= message_index < len(self._blocks)):
            return
        block = self._blocks[message_index]
        if not self._revertible(block):
            return
        self.post_message(self.RevertRequested(self, block.message_id))

    def action_toggle_section(self, block_index: int, section_index: int) -> None:
        """Expand/collapse an accordion section (thinking / tool result)."""
        if 0 <= block_index < len(self._blocks):
            block = self._blocks[block_index]
            if 0 <= section_index < len(block.sections):
                section = block.sections[section_index]
                section.collapsed = not section.collapsed
                self._rewrite_tail(block_index)

    def clear(self) -> 'MessagePane':
        """Clear the log and any active selection."""
        self._dirty_index = None
        self._status = None
        self._status_index = None
        self._agent_index.clear()
        self._blocks.clear()
        self._message_spans.clear()
        self._mount_start = 0
        self._mounted = False
        self._clear_selection()
        return super().clear()

    # --- selection helpers --------------------------------------------------

    @property
    def _has_selection(self) -> bool:
        return self._selection_start is not None and self._selection_end is not None

    def _clear_selection(self) -> None:
        """Drop the highlight.

        The drag anchor is left alone: re-renders (a streaming agent re-writes its
        block on every flush) must not end a drag the user is still holding.
        """
        self._selection_start = None
        self._selection_end = None
        self.refresh()

    def _virtual_offset(self, offset: Offset) -> tuple[int, int]:
        """Map a content-area offset to ``(row, col)`` in the log's virtual space."""
        scroll_x, scroll_y = self.scroll_offset
        row = min(max(scroll_y + offset.y, 0), max(len(self.lines) - 1, 0))
        col = max(scroll_x + offset.x, 0)
        return (row, col)

    def _span_for_row(self, row: int) -> int | None:
        """Return the index of the message whose rows contain ``row``, or ``None``."""
        for index, span in enumerate(self._message_spans):
            if span is not None and span[0] <= row < span[1]:
                return index
        return None

    def _column_range(self, row: int, start: tuple[int, int], end: tuple[int, int]) -> tuple[int, int]:
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

    def _fully_selected(self, index: int, start: tuple[int, int], end: tuple[int, int]) -> bool:
        """True when every cell of the message at ``index`` lies inside the selection."""
        span = self._message_spans[index]
        if span is None:
            return False
        span_start, span_end = span
        if span_start < start[0] or span_end - 1 > end[0]:
            return False
        if span_start == start[0] and start[1] > 0:
            return False
        if span_end - 1 == end[0]:
            row = span_end - 1
            line = self.lines[row].text if row < len(self.lines) else ''
            if end[1] < cell_len(line):
                return False
        return True

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
            if span_index is not None and self._fully_selected(span_index, start, end):
                selected.append(self._copy_text(self._blocks[span_index]))
                span = self._message_spans[span_index]
                row = span[1] if span is not None else row + 1
                continue
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

    def copy_selection(self) -> bool:
        """Copy the current mouse selection to the clipboards; False when there is none."""
        if not self._has_selection:
            return False
        text = self._selection_text()
        if not text:
            return False
        self._copy_to_clipboards(text)
        return True

    # --- mouse selection -----------------------------------------------------

    async def _on_mouse_down(self, event: events.MouseDown) -> None:
        if event.button == 1:  # left button
            offset = event.get_content_offset(self)
            if offset is not None:
                # Only a click inside the text starts a drag, and only then is the
                # mouse captured — so pressing the border, the padding or the
                # scrollbar cannot leave the capture behind.
                self._mouse_captured = True
                self.capture_mouse()
                self._selection_anchor = self._selection_start = self._selection_end = self._virtual_offset(offset)
                self.refresh()
            else:
                # Click on border/padding/scrollbar: drop any existing selection.
                self._selection_anchor = None
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
        # The capture is always let go here: while it is held every mouse event of
        # the app is routed to this pane, so the tab strip, the popup and the input
        # would silently stop answering clicks.
        if self._mouse_captured:
            self._mouse_captured = False
            self.release_mouse()
        if self._selection_anchor is not None:
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
