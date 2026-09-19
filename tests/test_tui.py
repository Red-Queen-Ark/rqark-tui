import asyncio
from collections.abc import Sequence

from rqark_app.types.session import SummaryMessage, message_from_dict
from rqark_core.types.chat import AssistantMessage, Message, SystemMessage, ToolMessage, UserMessage
from rqark_core.types.tool import PlanItem

from rqark_tui.tui import AgentTUI
from rqark_tui.tui.components.footer import ChatInput
from rqark_tui.tui.components.header import HeaderBar
from rqark_tui.tui.components.main import MessagePane
from rqark_tui.tui.components.popup import PopupSelector

PLAN_ITEM = PlanItem(id='1', content='do the thing', status='pending')


class StubTool:
    def __init__(self, name: str, display_key: str) -> None:
        self.name = name
        self.display_key = display_key


def rendered_text(pane: MessagePane) -> str:
    return '\n'.join(line.text for line in pane.lines)


async def test_header_shows_agent_model_and_title_updates():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        header = tui.query_one(HeaderBar)
        tui.set_agent_name('coder')
        tui.set_model_name('deepseek')
        tui.set_session_title('my session')
        assert (header.agent_name, header.model_name, header.session_title) == ('coder', 'deepseek', 'my session')
        assert 'coder' in str(header.render())


async def test_setters_before_running_store_values_without_querying():
    tui = AgentTUI()
    tui.set_agent_name('coder')
    tui.set_model_name('deepseek')
    tui.set_session_title('title')
    assert (tui._agent_name, tui._model_name, tui._session_title) == ('coder', 'deepseek', 'title')
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        header = tui.query_one(HeaderBar)
        assert (header.agent_name, header.model_name, header.session_title) == ('coder', 'deepseek', 'title')


async def test_tool_keys_are_forwarded_to_the_message_pane():
    tui = AgentTUI()
    tui.set_tools([StubTool('bash', 'cmd')])
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        assert tui.query_one(MessagePane)._tool_keys == {'bash': 'cmd'}


async def test_restored_user_message_is_replayed():
    tui = AgentTUI()
    tui.restore_session([UserMessage('hi')])
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        pane = tui.query_one(MessagePane)
        assert 'hi' in rendered_text(pane)
        assert tui._restore_messages is None


async def test_restored_user_message_with_content_parts_is_replayed():
    message = message_from_dict({'role': 'user', 'content': [{'type': 'text', 'text': 'restored parts'}], 'created_at': '2026-09-16T04:16:55.894142+00:00'})
    tui = AgentTUI()
    tui.restore_session([message])
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        pane = tui.query_one(MessagePane)
        assert 'restored parts' in rendered_text(pane)
        assert pane._blocks[0].sections[0].text == 'restored parts'


async def test_restored_reasoning_stays_collapsed():
    tui = AgentTUI()
    tui.restore_session([AssistantMessage(content='answer', reasoning_content='long reasoning')])
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        pane = tui.query_one(MessagePane)
        think = pane._blocks[0].sections[0]
        assert (think.mode, think.collapsed) == ('think', True)
        assert 'long reasoning' not in rendered_text(pane)
        assert 'answer' in rendered_text(pane)


async def test_restored_tool_message_is_replayed():
    tui = AgentTUI()
    history: Sequence[Message | SummaryMessage] = [ToolMessage(tool_call_id='1', content='tool output', tool_name='bash')]
    tui.restore_session(history)
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        pane = tui.query_one(MessagePane)
        assert pane._blocks[0].kind == 'tools'
        assert pane._blocks[0].sections[-1].text == 'tool output'


async def test_restored_summary_and_system_messages_are_replayed():
    tui = AgentTUI()
    history: Sequence[Message | SummaryMessage] = [SummaryMessage('summary text'), SystemMessage('system note')]
    tui.restore_session(history)
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        text = rendered_text(tui.query_one(MessagePane))
        assert 'summary text' in text
        assert 'system note' in text


async def test_restore_session_after_running_replays_immediately():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        tui.restore_session([UserMessage('late restore')])
        assert 'late restore' in rendered_text(tui.query_one(MessagePane))


async def test_append_helpers_reach_the_pane():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        tui.append_message('question')
        tui.append_think_delta('reasoning')
        tui.append_agent_delta('answer')
        tui.append_tool_call('bash', '{"cmd": "ls"}')
        tui.append_tool_result('bash', 'listing')
        tui.append_error('failed')
        tui.append_system('notice')
        tui.close_agent_message()
        pane = tui.query_one(MessagePane)
        assert [block.kind for block in pane._blocks] == ['user', 'agent', 'tools', 'system', 'system']
        text = rendered_text(pane)
        for fragment in ('question', 'thinking', 'answer', 'ls', 'failed', 'notice'):
            assert fragment in text
        assert 'reasoning' not in text
        pane.action_toggle_section(1, 0)
        assert 'reasoning' in rendered_text(pane)
        pane.action_toggle_section(2, 1)
        assert 'listing' in rendered_text(pane)


async def test_clear_messages_empties_the_pane():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        tui.append_message('question')
        tui.clear_messages()
        pane = tui.query_one(MessagePane)
        assert pane._blocks == []
        assert pane.lines == []


async def test_show_plan_renders_items_in_read_only_mode():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        popup = tui.query_one(PopupSelector)
        tui.show_plan([PLAN_ITEM])
        assert popup.display is True
        assert popup.selectable is False
        assert 'do the thing' in popup.render()
        assert tui.query_one(ChatInput).popup_active is False


async def test_empty_plan_hides_the_popup():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        popup = tui.query_one(PopupSelector)
        tui.show_plan([PLAN_ITEM])
        tui.show_plan([])
        assert popup.display is False


async def test_show_plan_does_not_replace_an_active_picker():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        popup = tui.query_one(PopupSelector)
        popup.show([('one', '1'), ('two', '2')])
        tui.show_plan([PLAN_ITEM])
        assert popup.selectable is True
        assert popup.selected_entry == ('one', '1')


async def test_show_plan_replaces_a_passive_plan_view():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        popup = tui.query_one(PopupSelector)
        popup.show_text('stale plan line')
        tui.show_plan([PLAN_ITEM])
        assert popup.selectable is False
        assert 'do the thing' in popup.render()
        assert 'stale plan line' not in popup.render()


async def test_pick_resolves_with_the_selected_entry():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        picker = pilot.app.run_worker(tui.pick([('one', '1'), ('two', '2')], title='Pick'))
        await pilot.pause()
        await pilot.press('down', 'enter')
        assert await picker.wait() == ('two', '2')
        assert tui.query_one(PopupSelector).display is False


async def test_pick_resolves_with_none_when_dismissed():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        picker = pilot.app.run_worker(tui.pick([('one', '1')]))
        await pilot.pause()
        await pilot.press('escape')
        assert await picker.wait() is None


async def test_pick_returns_none_for_an_empty_entry_list():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        assert await tui.pick([]) is None


async def test_chat_submission_reaches_the_handler():
    tui = AgentTUI()
    received: list[str] = []

    async def handler(text: str, images: list[str]) -> None:
        received.append(text)

    tui.set_chat_handler(handler)
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        tui.query_one(ChatInput).text = 'hello'
        await pilot.press('enter')
        await pilot.pause(0.1)
        assert received == ['hello']
        assert tui._chat_busy is False
        assert 'hello' in rendered_text(tui.query_one(MessagePane))


async def test_second_submission_is_rejected_while_busy():
    tui = AgentTUI()
    received: list[str] = []

    async def handler(text: str, images: list[str]) -> None:
        received.append(text)

    tui.set_chat_handler(handler)
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        tui._chat_busy = True
        tui.query_one(ChatInput).text = 'ignored'
        await pilot.press('enter')
        await pilot.pause(0.1)
        assert received == []
        assert tui.query_one(MessagePane)._blocks == []


async def test_chat_handler_errors_clear_the_busy_flag():
    tui = AgentTUI()

    async def handler(text: str, images: list[str]) -> None:
        raise RuntimeError('model exploded')

    tui.set_chat_handler(handler)
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        tui.query_one(ChatInput).text = 'hello'
        await pilot.press('enter')
        await pilot.pause(0.1)
        assert tui._chat_busy is False


async def test_cancel_chat_cancels_the_running_worker():
    tui = AgentTUI()
    started: list[str] = []

    async def handler(text: str, images: list[str]) -> None:
        started.append(text)
        await asyncio.sleep(30)

    tui.set_chat_handler(handler)
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        tui.query_one(ChatInput).text = 'long request'
        await pilot.press('enter')
        await pilot.pause(0.1)
        assert started == ['long request']
        assert tui._chat_worker is not None
        assert tui._chat_worker.is_running is True
        tui.cancel_chat()
        await pilot.pause(0.1)
        assert tui._chat_worker.is_running is False
        assert tui._chat_busy is False


async def test_cancel_chat_without_a_worker_is_safe():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        tui.cancel_chat()
        assert tui._chat_worker is None


async def test_slash_input_is_dispatched_to_the_command_handler():
    tui = AgentTUI()
    commands: list[str] = []

    async def handler(command: str) -> str | None:
        commands.append(command)
        return 'done'

    tui.set_command_handler(handler)
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        tui.query_one(ChatInput).text = '/clear'
        await pilot.press('enter')
        await pilot.pause(0.1)
        assert commands == ['/clear']
        assert 'done' in rendered_text(tui.query_one(MessagePane))


async def test_command_handler_errors_do_not_break_the_app():
    tui = AgentTUI()

    async def handler(command: str) -> str | None:
        raise RuntimeError('bad command')

    tui.set_command_handler(handler)
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        tui.query_one(ChatInput).text = '/nope'
        await pilot.press('enter')
        await pilot.pause(0.1)
        assert tui._chat_busy is False
        assert tui.query_one(MessagePane)._blocks == []


async def test_slash_text_without_a_command_handler_is_echoed_as_a_message():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        tui.query_one(ChatInput).text = '/clear'
        await pilot.press('enter')
        await pilot.pause(0.1)
        pane = tui.query_one(MessagePane)
        assert [block.kind for block in pane._blocks] == ['user']
        assert pane._blocks[0].sections[0].text == '/clear'


async def test_chat_input_without_a_handler_still_echoes_the_message():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        tui.query_one(ChatInput).text = 'echo me'
        await pilot.press('enter')
        await pilot.pause(0.1)
        assert 'echo me' in rendered_text(tui.query_one(MessagePane))


async def test_compose_yields_the_four_widgets_with_focus_on_the_input():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        assert len(tui.query(HeaderBar)) == 1
        assert len(tui.query(MessagePane)) == 1
        assert len(tui.query(PopupSelector)) == 1
        assert len(tui.query(ChatInput)) == 1
        assert tui.query_one(ChatInput).has_focus


async def test_auto_focus_points_at_the_chat_input():
    assert AgentTUI.AUTO_FOCUS == 'ChatInput'


async def test_screen_background_is_the_dark_theme_colour():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        assert tui.screen.styles.background.hex == '#141414'


async def test_submitted_images_reach_the_handler(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'photo.png').write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 16)
    tui = AgentTUI()
    received: list[tuple[str, list[str]]] = []

    async def handler(text: str, images: list[str]) -> None:
        received.append((text, images))

    tui.set_chat_handler(handler)
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        tui.query_one(ChatInput).text = 'see @!photo.png'
        await pilot.press('enter')
        await pilot.pause(0.1)
        assert received[0][0] == 'see'
        assert len(received[0][1]) == 1
        assert received[0][1][0].startswith('data:image/png;base64,')
        assert '[image 1]' in rendered_text(tui.query_one(MessagePane))


async def test_restored_user_message_with_images_is_replayed():
    tui = AgentTUI()
    tui.restore_session([UserMessage('old picture', images=['data:image/png;base64,AAAA'])])
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        text = rendered_text(tui.query_one(MessagePane))
        assert 'old picture' in text
        assert '[image 1]' in text
