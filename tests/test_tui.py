import asyncio
from collections.abc import Sequence

from rqark_app.types.session import SummaryMessage, message_from_dict
from rqark_core.types.chat import AssistantMessage, Message, SystemMessage, ToolMessage, UserMessage
from rqark_core.types.tool import PlanItem
from textual.widgets import Static

from rqark_tui.tui import AgentTUI
from rqark_tui.tui.components.footer import ChatInput
from rqark_tui.tui.components.header import HeaderBar
from rqark_tui.tui.components.main import MessagePane
from rqark_tui.tui.components.popup import PopupSelector
from rqark_tui.tui.components.session import SessionTabs

PLAN_ITEM = PlanItem(id='1', content='do the thing', status='pending')


class StubTool:
    def __init__(self, name: str, display_key: str) -> None:
        self.name = name
        self.display_key = display_key


class StubBridge:
    """Minimal SessionHandler: records what it is asked to do, can block, error or reply."""

    def __init__(self, delay: float = 0.0, error: BaseException | None = None, reply: str | None = None) -> None:
        self.delay = delay
        self.error = error
        self.reply = reply
        self.chats: list[tuple[str, list[str]]] = []
        self.commands: list[str] = []
        self.keys: list[str] = []

    async def chat(self, text: str, images: list[str] | None = None) -> None:
        self.chats.append((text, list(images) if images else []))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error

    async def command(self, command: str) -> str | None:
        self.commands.append(command)
        if self.error is not None:
            raise self.error
        return self.reply


def bridge_factory(bridge: StubBridge):
    def factory(key: str, session_id: str | None) -> StubBridge:
        bridge.keys.append(key)
        return bridge

    return factory


def rendered_text(pane: MessagePane) -> str:
    return '\n'.join(line.text for line in pane.lines)


async def test_header_shows_agent_and_model_updates():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        header = tui.query_one(HeaderBar)
        tui.set_agent_name('coder')
        tui.set_model_name('deepseek')
        assert (header.agent_name, header.model_name) == ('coder', 'deepseek')
        assert 'coder' in str(header.query_one('.header-line', Static).render())


async def test_header_shows_the_cloud_badge_in_cloud_mode():
    tui = AgentTUI()
    tui.set_cloud_mode(True)
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        header = tui.query_one(HeaderBar)
        assert header.cloud is True
        assert header.query_one('.header-cloud', Static).display


async def test_header_hides_the_cloud_badge_outside_cloud_mode():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        header = tui.query_one(HeaderBar)
        assert header.cloud is False
        assert not header.query_one('.header-cloud', Static).display


async def test_setters_before_running_store_values_without_querying():
    tui = AgentTUI()
    tui.set_agent_name('coder')
    tui.set_model_name('deepseek')
    tui.open_sessions([('stored-uuid', 'title', [])])
    assert (tui._agent_name, tui._model_name) == ('coder', 'deepseek')
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        header = tui.query_one(HeaderBar)
        assert (header.agent_name, header.model_name) == ('coder', 'deepseek')
        assert tui.active_session.session_id == 'stored-uuid'


async def test_tool_keys_are_forwarded_to_the_message_pane():
    tui = AgentTUI()
    tui.set_tools([StubTool('bash', 'cmd')])
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        assert tui.query_one(MessagePane)._tool_keys == {'bash': 'cmd'}


async def test_restored_user_message_is_replayed():
    tui = AgentTUI()
    tui.open_sessions([('stored-uuid', '', [UserMessage('hi')])])
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        pane = tui.query_one(MessagePane)
        assert 'hi' in rendered_text(pane)
        assert tui._pending == []


async def test_restored_user_message_with_content_parts_is_replayed():
    message = message_from_dict({'role': 'user', 'content': [{'type': 'text', 'text': 'restored parts'}], 'created_at': '2026-09-16T04:16:55.894142+00:00'})
    tui = AgentTUI()
    tui.open_sessions([('stored-uuid', '', [message])])
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        pane = tui.query_one(MessagePane)
        assert 'restored parts' in rendered_text(pane)
        assert pane._blocks[0].sections[0].text == 'restored parts'


async def test_restored_reasoning_stays_collapsed():
    tui = AgentTUI()
    tui.open_sessions([('stored-uuid', '', [AssistantMessage(content='answer', reasoning_content='long reasoning')])])
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
    tui.open_sessions([('stored-uuid', '', history)])
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        pane = tui.query_one(MessagePane)
        assert pane._blocks[0].kind == 'tools'
        assert pane._blocks[0].sections[-1].text == 'tool output'


async def test_restored_summary_and_system_messages_are_replayed():
    tui = AgentTUI()
    history: Sequence[Message | SummaryMessage] = [SummaryMessage('summary text'), SystemMessage('system note')]
    tui.open_sessions([('stored-uuid', '', history)])
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        text = rendered_text(tui.query_one(MessagePane))
        assert 'summary text' in text
        assert 'system note' in text


async def test_open_sessions_while_running_adds_tabs():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        tui.open_sessions([('stored-uuid', 'stored', [UserMessage('late restore')])])
        await pilot.pause()
        assert tui.active_session.session_id == 'stored-uuid'
        assert 'late restore' in rendered_text(tui.pane)
        assert tui.query_one(SessionTabs).tab_count == 3


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
    bridge = StubBridge()
    tui.set_session_factory(bridge_factory(bridge))
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        tui.query_one(ChatInput).text = 'hello'
        await pilot.press('enter')
        await pilot.pause(0.1)
        assert bridge.chats == [('hello', [])]
        assert bridge.keys == ['session-1']
        assert tui.active_session.busy is False
        assert 'hello' in rendered_text(tui.query_one(MessagePane))


async def test_second_submission_is_rejected_while_busy():
    tui = AgentTUI()
    bridge = StubBridge()
    tui.set_session_factory(bridge_factory(bridge))
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        tui.active_session.busy = True
        tui.query_one(ChatInput).text = 'ignored'
        await pilot.press('enter')
        await pilot.pause(0.1)
        assert bridge.chats == []
        assert tui.query_one(MessagePane)._blocks == []


async def test_chat_handler_errors_clear_the_busy_flag():
    tui = AgentTUI()
    bridge = StubBridge(error=RuntimeError('model exploded'))
    tui.set_session_factory(bridge_factory(bridge))
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        tui.query_one(ChatInput).text = 'hello'
        await pilot.press('enter')
        await pilot.pause(0.1)
        assert tui.active_session.busy is False


async def test_cancel_chat_cancels_the_running_worker():
    tui = AgentTUI()
    bridge = StubBridge(delay=30)
    tui.set_session_factory(bridge_factory(bridge))
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        tui.query_one(ChatInput).text = 'long request'
        await pilot.press('enter')
        await pilot.pause(0.1)
        assert bridge.chats == [('long request', [])]
        worker = tui.active_session.worker
        assert worker is not None
        assert worker.is_running is True
        tui.cancel_chat()
        await pilot.pause(0.1)
        assert worker.is_running is False
        assert tui.active_session.busy is False


async def test_cancel_chat_without_a_worker_is_safe():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        tui.cancel_chat()
        assert tui.active_session.worker is None


async def test_slash_input_is_dispatched_to_the_command_handler():
    tui = AgentTUI()
    bridge = StubBridge(reply='done')
    tui.set_session_factory(bridge_factory(bridge))
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        tui.query_one(ChatInput).text = '/clear'
        await pilot.press('enter')
        await pilot.pause(0.1)
        assert bridge.commands == ['/clear']
        assert 'done' in rendered_text(tui.query_one(MessagePane))


async def test_command_handler_errors_do_not_break_the_app():
    tui = AgentTUI()
    bridge = StubBridge(error=RuntimeError('bad command'))
    tui.set_session_factory(bridge_factory(bridge))
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        tui.query_one(ChatInput).text = '/nope'
        await pilot.press('enter')
        await pilot.pause(0.1)
        assert tui.active_session.busy is False
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


async def test_compose_yields_one_widget_of_each_kind_with_focus_on_the_input():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        assert len(tui.query(HeaderBar)) == 1
        assert len(tui.query(SessionTabs)) == 1
        assert len(tui.query(MessagePane)) == 1
        assert len(tui.query(PopupSelector)) == 1
        assert len(tui.query(ChatInput)) == 1
        assert tui.query_one(ChatInput).has_focus


async def test_widgets_stack_in_header_tabs_main_popup_footer_order():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        header = tui.query_one(HeaderBar).region
        tabs = tui.query_one(SessionTabs).region
        pane = tui.query_one(MessagePane).region
        chat = tui.query_one(ChatInput).region
        assert header.y + header.height == tabs.y
        assert tabs.y + tabs.height == pane.y
        assert pane.y + pane.height <= chat.y


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
    bridge = StubBridge()
    tui.set_session_factory(bridge_factory(bridge))
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        tui.query_one(ChatInput).text = 'see @!photo.png'
        await pilot.press('enter')
        await pilot.pause(0.1)
        text, images = bridge.chats[0]
        assert text == 'see'
        assert len(images) == 1
        assert images[0].startswith('data:image/png;base64,')
        assert '[image 1]' in rendered_text(tui.query_one(MessagePane))


async def test_restored_user_message_with_images_is_replayed():
    tui = AgentTUI()
    tui.open_sessions([('stored-uuid', '', [UserMessage('old picture', images=['data:image/png;base64,AAAA'])])])
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        text = rendered_text(tui.query_one(MessagePane))
        assert 'old picture' in text
        assert '[image 1]' in text
