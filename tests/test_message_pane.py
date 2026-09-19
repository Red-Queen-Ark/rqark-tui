import asyncio
from datetime import UTC, datetime

import pytest
from rich.color import Color
from rich.control import Control
from rich.segment import Segment
from rich.style import Style
from textual import events
from textual.app import App, ComposeResult
from textual.geometry import Offset
from textual.strip import Strip

from rqark_tui.tui.components import main as main_module
from rqark_tui.tui.components.main import MessagePane, _apply_selection_style, _crop_plain

SELECTION_COLOR = Color.parse(main_module._SELECTION_BG)


class PaneApp(App[None]):
    def compose(self) -> ComposeResult:
        yield MessagePane()


def rendered_text(pane: MessagePane) -> str:
    return '\n'.join(line.text for line in pane.lines)


def track_renders(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []
    original = MessagePane._rewrite_tail

    def counting(self: MessagePane, index: int) -> None:
        calls.append(index)
        original(self, index)

    monkeypatch.setattr(MessagePane, '_rewrite_tail', counting)
    return calls


async def test_streaming_deltas_are_batched_into_a_single_render(monkeypatch):
    calls = track_renders(monkeypatch)
    async with PaneApp().run_test(size=(40, 100)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        for _ in range(60):
            pane.append_agent_delta('token ')
        assert calls == []
        assert pane._dirty_index == 0
        await pilot.pause(0.4)
        assert calls == [0]
        assert pane._dirty_index is None


async def test_render_count_stays_far_below_delta_count(monkeypatch):
    calls = track_renders(monkeypatch)
    async with PaneApp().run_test(size=(40, 100)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        calls.clear()
        for _ in range(60):
            pane.append_agent_delta('x')
            await asyncio.sleep(0.005)
        pane._flush_now()
        assert 0 < len(calls) <= 5


async def test_streamed_text_is_fully_rendered_after_close():
    async with PaneApp().run_test(size=(40, 100)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        for _ in range(40):
            pane.append_agent_delta('word ')
        pane.append_think_delta('because ')
        pane.close_agent_message()
        block = pane._blocks[0]
        body = next(section for section in block.sections if section.mode == 'body')
        assert body.text == 'word ' * 40
        assert 'word word word' in rendered_text(pane)
        assert pane._dirty_index is None


async def test_think_delta_accumulates_into_the_first_section():
    async with PaneApp().run_test(size=(40, 100)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        pane.append_agent_delta('answer')
        pane.append_think_delta('first ')
        pane.append_think_delta('second ')
        sections = pane._blocks[0].sections
        assert [section.mode for section in sections] == ['think', 'body']
        assert sections[0].text == 'first second '
        assert sections[0].collapsed is True
        assert sections[1].text == 'answer'


async def test_tool_call_flushes_the_pending_stream(monkeypatch):
    calls = track_renders(monkeypatch)
    async with PaneApp().run_test(size=(40, 100)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        calls.clear()
        pane.append_agent_delta('partial ')
        assert calls == []
        pane.append_tool_call('read_file', '{"path": "a.py"}')
        assert calls == [0, 1]
        assert pane._dirty_index is None
        assert 'partial' in rendered_text(pane)


async def test_pending_stream_is_rendered_before_a_new_user_message(monkeypatch):
    calls = track_renders(monkeypatch)
    async with PaneApp().run_test(size=(40, 100)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        calls.clear()
        pane.append_agent_delta('streamed')
        pane.append_message('next question')
        assert calls == [0, 1]
        assert [block.kind for block in pane._blocks] == ['agent', 'user']


async def test_pending_stream_is_rendered_before_system_and_error_blocks(monkeypatch):
    calls = track_renders(monkeypatch)
    async with PaneApp().run_test(size=(40, 100)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        calls.clear()
        pane.append_agent_delta('streamed')
        pane.append_error('boom')
        pane.append_system('note')
        assert calls == [0, 1, 2]
        assert [block.kind for block in pane._blocks] == ['agent', 'system', 'system']


async def test_close_agent_message_flushes_pending_stream(monkeypatch):
    calls = track_renders(monkeypatch)
    async with PaneApp().run_test(size=(40, 100)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        calls.clear()
        pane.append_agent_delta('streamed')
        assert calls == []
        pane.close_agent_message()
        assert calls == [0]


async def test_tool_result_flushes_pending_stream():
    async with PaneApp().run_test(size=(40, 100)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        pane.append_agent_delta('streamed')
        pane.append_tool_result('bash', 'output')
        assert pane._dirty_index is None
        assert 'streamed' in rendered_text(pane)


async def test_mark_dirty_keeps_the_earliest_pending_index():
    async with PaneApp().run_test(size=(40, 100)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        for text in ('one', 'two', 'three'):
            pane.append_message(text)
        pane._mark_dirty(1)
        pane._mark_dirty(2)
        assert pane._dirty_index == 1
        pane._mark_dirty(0)
        assert pane._dirty_index == 0
        pane._flush_now()
        assert pane._dirty_index is None


async def test_flush_now_without_dirty_state_is_a_noop(monkeypatch):
    calls = track_renders(monkeypatch)
    async with PaneApp().run_test(size=(40, 100)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        calls.clear()
        pane._flush_now()
        pane._flush_now()
        assert calls == []


async def test_clear_drops_the_pending_stream():
    async with PaneApp().run_test(size=(40, 100)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        pane.append_agent_delta('stale ')
        assert pane._dirty_index == 0
        assert pane.clear() is pane
        assert pane._dirty_index is None
        assert pane._blocks == []
        assert pane.lines == []
        assert pane._message_spans == []
        await pilot.pause(0.3)
        assert 'stale' not in rendered_text(pane)


async def test_text_streamed_after_clear_renders_without_the_stale_prefix():
    async with PaneApp().run_test(size=(40, 100)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        pane.append_agent_delta('stale ')
        pane.clear()
        pane.append_agent_delta('fresh ')
        pane.close_agent_message()
        text = rendered_text(pane)
        assert 'fresh' in text
        assert 'stale' not in text


async def test_rebuild_resets_dirty_state_and_recomputes_spans():
    async with PaneApp().run_test(size=(40, 100)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        pane.append_message('one')
        pane.append_agent_delta('two')
        pane._mark_dirty(0)
        pane._rebuild()
        assert pane._dirty_index is None
        assert len(pane._message_spans) == len(pane._blocks)
        assert len(pane._message_texts) == len(pane._blocks)
        assert 'two' in rendered_text(pane)


async def test_submitted_message_starts_a_user_block():
    async with PaneApp().run_test(size=(40, 100)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        pane.append_message('hello there')
        assert [block.kind for block in pane._blocks] == ['user']
        assert 'hello there' in rendered_text(pane)


async def test_agent_delta_after_a_tool_section_starts_a_new_agent_block():
    async with PaneApp().run_test(size=(40, 100)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        pane.append_agent_delta('before')
        pane.append_tool_call('bash', '{}')
        pane.append_agent_delta('after')
        assert [block.kind for block in pane._blocks] == ['agent', 'tools', 'agent']
        assert pane._blocks[0].open is False
        assert pane._blocks[2].sections[-1].text == 'after'


async def test_tool_result_reuses_an_open_tools_block():
    async with PaneApp().run_test(size=(40, 100)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        pane.append_tool_call('bash', '{"cmd": "ls"}')
        pane.append_tool_result('bash', '  result body  ')
        assert [block.kind for block in pane._blocks] == ['tools']
        assert pane._blocks[0].open is True
        modes = [section.mode for section in pane._blocks[0].sections]
        assert modes == ['tool', 'result']
        result = pane._blocks[0].sections[1]
        assert result.text == 'result body'
        assert result.collapsed is True


async def test_tool_result_without_a_tool_call_starts_a_tools_block():
    async with PaneApp().run_test(size=(40, 100)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        pane.append_tool_result('', 'output')
        assert [block.kind for block in pane._blocks] == ['tools']
        assert pane._blocks[0].sections[0].name == 'tool'


async def test_error_block_uses_the_system_kind():
    async with PaneApp().run_test(size=(40, 100)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        pane.append_error('something broke')
        assert [block.kind for block in pane._blocks] == ['system']
        assert pane._blocks[0].sections[0].mode == 'error'
        assert 'something broke' in rendered_text(pane)


async def test_copy_text_includes_tool_arguments_and_results():
    async with PaneApp().run_test(size=(40, 100)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        pane.append_message('question')
        pane.append_tool_call('bash', '{"cmd": "ls -la"}')
        pane.append_tool_result('bash', 'file list')
        pane.set_tool_keys({'bash': 'cmd'})
        assert pane._copy_text(pane._blocks[0]) == 'User\nquestion'
        assert pane._copy_text(pane._blocks[1]) == 'Agent\nuse tool bash ls -la\nfile list'


async def test_tool_display_falls_back_to_raw_arguments_on_bad_json():
    async with PaneApp().run_test(size=(40, 100)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        pane.set_tool_keys({'bash': 'cmd'})
        pane.append_tool_call('bash', 'not json at all')
        assert 'not json at all' in pane._copy_text(pane._blocks[0])


async def test_tool_display_is_truncated_without_a_display_key():
    async with PaneApp().run_test(size=(40, 100)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        pane.append_tool_call('bash', 'x' * 100)
        section = pane._blocks[0].sections[0]
        assert pane._tool_display(section) == 'x' * 40


async def test_action_copy_message_copies_whole_block_and_clears_selection(monkeypatch):
    copied: list[str] = []
    monkeypatch.setattr(main_module, 'write_system_clipboard', copied.append)
    async with PaneApp().run_test(size=(40, 100)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        pane.append_message('question')
        pane._selection_start = (0, 0)
        pane._selection_end = (0, 1)
        pane.action_copy_message(0)
        assert copied == ['User\nquestion']
        assert pilot.app.clipboard == 'User\nquestion'
        assert pane._has_selection is False


async def test_action_copy_message_ignores_out_of_range_indices(monkeypatch):
    copied: list[str] = []
    monkeypatch.setattr(main_module, 'write_system_clipboard', copied.append)
    async with PaneApp().run_test(size=(40, 100)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        pane.append_message('question')
        pane.action_copy_message(-1)
        pane.action_copy_message(5)
        assert copied == []


async def test_copy_message_uses_live_text_before_the_next_flush(monkeypatch):
    copied: list[str] = []
    monkeypatch.setattr(main_module, 'write_system_clipboard', copied.append)
    async with PaneApp().run_test(size=(40, 100)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        pane.append_agent_delta('unflushed tail')
        pane.action_copy_message(0)
        assert copied == ['Agent\nunflushed tail']


async def test_action_toggle_section_rewrites_the_last_block():
    async with PaneApp().run_test(size=(40, 100)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        pane.append_agent_delta('body')
        pane.append_think_delta('reasoning text')
        pane.action_toggle_section(0, 0)
        assert pane._blocks[0].sections[0].collapsed is False
        assert 'reasoning text' in rendered_text(pane)
        pane.action_toggle_section(0, 0)
        assert pane._blocks[0].sections[0].collapsed is True
        assert 'reasoning text' not in rendered_text(pane)


async def test_action_toggle_section_rebuilds_an_earlier_block():
    async with PaneApp().run_test(size=(40, 100)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        pane.append_agent_delta('body')
        pane.append_think_delta('reasoning text')
        pane.append_message('later message')
        pane.action_toggle_section(0, 0)
        assert pane._blocks[0].sections[0].collapsed is False
        assert 'reasoning text' in rendered_text(pane)
        assert 'later message' in rendered_text(pane)


async def test_action_toggle_section_ignores_out_of_range_indices():
    async with PaneApp().run_test(size=(40, 100)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        pane.append_agent_delta('body')
        pane.action_toggle_section(3, 0)
        pane.action_toggle_section(0, 9)
        assert pane._blocks[0].sections[-1].text == 'body'


async def test_format_time_localises_aware_timestamps():
    aware = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert MessagePane._format_time(aware) == aware.astimezone().strftime('%Y-%m-%d %H:%M:%S')
    naive = datetime(2026, 1, 2, 3, 4, 5)
    assert MessagePane._format_time(naive) == '2026-01-02 03:04:05'


@pytest.mark.parametrize(
    ('text', 'start', 'end', 'expected'),
    [
        ('abcdef', 0, 6, 'abcdef'),
        ('abcdef', 2, 4, 'cd'),
        ('abcdef', 4, 2, ''),
        ('abcdef', 0, 99, 'abcdef'),
        ('abcdef', 99, 100, ''),
        ('你好世界', 0, 4, '你好'),
        ('你好世界', 2, 6, '好世'),
        ('你好世界', 0, 3, '你'),
    ],
)
def test_crop_plain_slices_by_cell_width(text, start, end, expected):
    assert _crop_plain(text, start, end) == expected


def test_apply_selection_style_highlights_only_the_selected_cells():
    strip = Strip([Segment('abcdef')], 6)
    styled = _apply_selection_style(strip, 2, 4)
    assert styled.text == 'abcdef'
    assert styled.cell_length == 6
    highlighted = ''.join(segment.text for segment in styled._segments if segment.style and segment.style.bgcolor == SELECTION_COLOR)
    assert highlighted == 'cd'


def test_apply_selection_style_keeps_control_segments_untouched():
    control = Control.move_to(0, 0)
    strip = Strip([Segment('', Style(), control), Segment('abc')], 3)
    styled = _apply_selection_style(strip, 0, 3)
    assert styled._segments[0].control is control
    assert ''.join(segment.text for segment in styled._segments) == 'abc'
    assert all(segment.style is not None and segment.style.bgcolor == SELECTION_COLOR for segment in styled._segments[1:])


def test_apply_selection_style_is_a_noop_for_an_empty_range():
    strip = Strip([Segment('abc')], 3)
    styled = _apply_selection_style(strip, 1, 1)
    assert all(segment.style is None or segment.style.bgcolor is None for segment in styled._segments)


async def test_whole_message_selection_returns_unwrapped_text():
    async with PaneApp().run_test(size=(20, 40)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        text = 'alpha beta gamma delta epsilon zeta eta theta iota kappa lambda'
        pane.append_message(text)
        start, end = pane._message_spans[0]
        assert end - start > 1
        pane._selection_start = (start, 0)
        pane._selection_end = (end - 1, main_module._END_OF_LINE)
        assert pane._selection_text() == pane._copy_text(pane._blocks[0])


async def test_select_all_returns_unwrapped_text_for_every_message():
    async with PaneApp().run_test(size=(20, 40)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        pane.append_message('alpha beta gamma delta epsilon zeta eta theta iota')
        pane.append_agent_delta('kappa lambda mu nu xi omicron pi rho sigma tau')
        pane.close_agent_message()
        assert all(end - start > 1 for start, end in pane._message_spans)
        pane._selection_start = (0, 0)
        pane._selection_end = (len(pane.lines) - 1, main_module._END_OF_LINE)
        assert pane._selection_text() == '\n'.join(pane._message_texts)


async def test_selection_ending_inside_a_message_crops_its_last_row():
    async with PaneApp().run_test(size=(20, 40)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        pane.append_message('abcdefghij')
        start, end = pane._message_spans[0]
        pane._selection_start = (start, 0)
        pane._selection_end = (end - 1, 4)
        rows = pane._selection_text().split('\n')
        assert rows[0].startswith('User')
        assert rows[1] == 'abcd'


async def test_partial_selection_crops_rows_to_the_dragged_columns():
    async with PaneApp().run_test(size=(20, 40)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        pane.append_message('abcdefghij')
        pane._selection_start = (1, 0)
        pane._selection_end = (1, 4)
        assert pane._selection_text() == 'abcd'


async def test_selection_spanning_rows_keeps_the_middle_rows_whole():
    async with PaneApp().run_test(size=(20, 40)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        pane.append_message('abcdefghij')
        pane.append_message('klmnopqrst')
        pane.append_message('uvwxyz')
        pane._selection_start = (1, 2)
        pane._selection_end = (5, 3)
        rows = pane._selection_text().split('\n')
        assert rows[0] == 'cdefghij'
        assert rows[1] == 'User'
        assert rows[2] == 'klmnopqrst'
        assert rows[3].startswith('User')
        assert rows[4] == 'uvw'


async def test_selection_text_is_empty_without_a_selection():
    async with PaneApp().run_test(size=(40, 100)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        pane.append_message('text')
        assert pane._selection_text() == ''
        assert pane.copy_selection() is False


async def test_column_range_clips_the_first_and_last_rows():
    async with PaneApp().run_test(size=(20, 40)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        assert pane._column_range(0, (0, 3), (0, 7)) == (3, 7)
        assert pane._column_range(3, (3, 2), (5, 4)) == (2, main_module._END_OF_LINE)
        assert pane._column_range(4, (3, 2), (5, 4)) == (0, main_module._END_OF_LINE)
        assert pane._column_range(5, (3, 2), (5, 4)) == (0, 4)


async def test_span_for_row_maps_rows_to_message_indices():
    async with PaneApp().run_test(size=(40, 100)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        pane.append_message('first')
        pane.append_message('second')
        first, second = pane._message_spans
        assert pane._span_for_row(first[0]) == 0
        assert pane._span_for_row(second[0]) == 1
        assert pane._span_for_row(second[1] + 5) is None


async def test_virtual_offset_clamps_to_the_available_lines():
    async with PaneApp().run_test(size=(40, 100)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        pane.append_message('only line')
        row, column = pane._virtual_offset(Offset(0, 999))
        assert row == len(pane.lines) - 1
        assert column >= 0


async def test_copy_selection_returns_true_when_text_is_selected(monkeypatch):
    copied: list[str] = []
    monkeypatch.setattr(main_module, 'write_system_clipboard', copied.append)
    async with PaneApp().run_test(size=(20, 40)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        pane.append_message('abcdefghij')
        pane._selection_start = (1, 0)
        pane._selection_end = (1, 4)
        assert pane.copy_selection() is True
        assert copied == ['abcd']
        pane._clear_selection()
        assert pane.copy_selection() is False


async def test_copy_to_clipboards_sets_both_clipboards_and_notifies(monkeypatch):
    copied: list[str] = []
    monkeypatch.setattr(main_module, 'write_system_clipboard', copied.append)
    async with PaneApp().run_test(size=(20, 40)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        pane._copy_to_clipboards('payload')
        assert copied == ['payload']
        assert pilot.app.clipboard == 'payload'


async def test_ctrl_a_selects_every_row_and_ctrl_c_copies(monkeypatch):
    copied: list[str] = []
    monkeypatch.setattr(main_module, 'write_system_clipboard', copied.append)
    async with PaneApp().run_test(size=(20, 40)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        pane.focus()
        await pilot.pause()
        pane.append_message('abcdefghij')
        await pilot.press('ctrl+a')
        assert pane._selection_start == (0, 0)
        assert pane._selection_end[0] == len(pane.lines) - 1
        await pilot.press('ctrl+c')
        assert copied == [pane._copy_text(pane._blocks[0])]


def content_offset(pane: MessagePane, x: int, y: int) -> tuple[int, int]:
    base = pane.content_region.offset - pane.region.offset
    return (base.x + x, base.y + y)


async def test_mouse_drag_selects_the_dragged_rows():
    async with PaneApp().run_test(size=(20, 40)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        pane.append_message('abcdefghij')
        pane.append_message('klmnopqrst')
        await pilot.mouse_down(MessagePane, offset=content_offset(pane, 2, 1))
        assert pane._selection_anchor is not None
        await pilot._post_mouse_events([events.MouseMove], MessagePane, offset=content_offset(pane, 4, 3), button=1)
        assert pane._has_selection is True
        await pilot.mouse_up(MessagePane, offset=content_offset(pane, 4, 3))
        assert pane._has_selection is True
        assert pane._selection_anchor is None
        assert pane._selection_start[0] == 1
        assert pane._selection_end[0] == 3


async def test_single_click_without_drag_clears_the_selection():
    async with PaneApp().run_test(size=(20, 40)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        pane.append_message('abcdefghij')
        pane._selection_start = (0, 0)
        pane._selection_end = (0, 4)
        await pilot.mouse_down(MessagePane, offset=content_offset(pane, 2, 1))
        assert pane._selection_anchor is not None
        await pilot.mouse_up(MessagePane, offset=content_offset(pane, 2, 1))
        assert pane._has_selection is False
        assert pane._selection_anchor is None


@pytest.mark.parametrize(
    ('value', 'expected'),
    [
        ('plain text', 'plain text'),
        ([{'type': 'text', 'text': 'one'}, {'type': 'text', 'text': 'two'}], 'one\ntwo'),
        ([], ''),
        (None, ''),
        ({'type': 'image_url', 'image_url': {'url': 'https://example.com/a.png'}}, ''),
        ({'type': 'text', 'text': 'wrapped'}, 'wrapped'),
        (42, '42'),
    ],
)
def test_content_text_normalises_provider_content_parts(value, expected):
    assert main_module._content_text(value) == expected


async def test_user_message_with_content_parts_renders_its_text():
    async with PaneApp().run_test(size=(20, 40)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        pane.append_message([{'type': 'text', 'text': '@src/rqark_tui/tui/ 點解佢成日會整死我 vscode'}])
        assert '@src/rqark_tui/tui/ 點解佢成日會整死我 vscode' in rendered_text(pane).replace('\n', '')
        assert pane._blocks[0].sections[0].text == '@src/rqark_tui/tui/ 點解佢成日會整死我 vscode'
        assert pane._message_texts[0].endswith('@src/rqark_tui/tui/ 點解佢成日會整死我 vscode')


async def test_streaming_delta_accepts_content_parts():
    async with PaneApp().run_test(size=(20, 40)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        pane.append_agent_delta('start ')
        pane.append_agent_delta([{'type': 'text', 'text': 'end'}])
        pane.close_agent_message()
        assert 'start end' in rendered_text(pane)


async def test_think_delta_accepts_content_parts():
    async with PaneApp().run_test(size=(20, 40)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        pane.append_think_delta([{'type': 'text', 'text': 'binary search'}])
        assert pane._blocks[0].sections[0].text == 'binary search'


async def test_user_message_with_images_renders_placeholders():
    async with PaneApp().run_test(size=(20, 60)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        pane.append_message('look at this', images=['data:image/png;base64,AAAA', 'data:image/png;base64,BBBB'])
        text = rendered_text(pane)
        assert '[image 1]' in text
        assert '[image 2]' in text
        assert pane._blocks[0].sections[0].text == 'look at this'
        assert pane._message_texts[0].endswith('[image 2]')


async def test_image_only_message_renders_without_a_body():
    async with PaneApp().run_test(size=(20, 60)) as pilot:
        pane = pilot.app.query_one(MessagePane)
        await pilot.pause()
        pane.append_message('', images=['data:image/png;base64,AAAA'])
        assert [section.mode for section in pane._blocks[0].sections] == ['image']
        assert '[image 1]' in rendered_text(pane)
