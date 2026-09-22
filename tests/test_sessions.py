import asyncio
from collections.abc import Sequence

from rqark_core.types.chat import UserMessage
from rqark_core.types.tool import PlanItem
from textual.widgets import Label

from rqark_tui.tui import AgentTUI
from rqark_tui.tui.components.dialog import YesNoDialog
from rqark_tui.tui.components.footer import ChatInput
from rqark_tui.tui.components.header import HeaderBar
from rqark_tui.tui.components.main import MessagePane
from rqark_tui.tui.components.popup import PopupSelector
from rqark_tui.tui.components.session import CLOSE_MARK, SessionTabs

PLAN_ITEM = PlanItem(id='1', content='do the thing', status='pending')


class StubTool:
    def __init__(self, name: str, display_key: str) -> None:
        self.name = name
        self.display_key = display_key


class Bridge:
    """Minimal SessionHandler that records what a session was asked to do."""

    def __init__(self, delay: float = 0.0, reply: str | None = None) -> None:
        self.delay = delay
        self.reply = reply
        self.chats: list[str] = []
        self.commands: list[str] = []
        self.closes = 0

    async def chat(self, text: str, images: list[str] | None = None) -> None:
        self.chats.append(text)
        if self.delay:
            await asyncio.sleep(self.delay)

    async def command(self, command: str) -> str | None:
        self.commands.append(command)
        return self.reply

    async def close(self) -> None:
        self.closes += 1


class Bridges:
    """Session factory handing out one Bridge per tab."""

    def __init__(self, delay: float = 0.0, reply: str | None = None) -> None:
        self.delay = delay
        self.reply = reply
        self.by_key: dict[str, Bridge] = {}

    def __call__(self, key: str, session_id: str | None) -> Bridge:
        bridge = Bridge(self.delay, self.reply)
        self.by_key[key] = bridge
        return bridge


def tabs_of(tui: AgentTUI) -> SessionTabs:
    return tui.query_one(SessionTabs)


def tab_labels(tui: AgentTUI) -> list[str]:
    """Tab labels without the close mark a session tab carries."""
    return [tab.label_text.removesuffix(CLOSE_MARK) for tab in tabs_of(tui).query('Tab')]


def pane_of(tui: AgentTUI, key: str) -> MessagePane:
    pane = tui.session_pane(key)
    assert pane is not None
    return pane


def sections_of(pane: MessagePane) -> str:
    return '\n'.join(section.text for block in pane._blocks for section in block.sections if section.text)


def rendered(pane: MessagePane) -> str:
    return '\n'.join(line.text for line in pane.lines)


def submit(tui: AgentTUI, text: str) -> None:
    tui.query_one(ChatInput).text = text
    tui.query_one(ChatInput).submit()


async def close_and_confirm(tui: AgentTUI, pilot, key: str) -> None:
    """Ask to close ``key`` and accept the confirmation dialog."""
    tui.close_session(key)
    await pilot.pause()
    await pilot.click('#yes')
    await pilot.pause()


async def test_the_first_session_tab_is_ready_on_mount():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        assert tab_labels(tui) == ['Session 1', '+']
        assert tui.active_key == 'session-1'
        assert pane_of(tui, 'session-1').display is True
        assert tui.query_one(HeaderBar).session_title == ''


async def test_the_plus_tab_adds_a_session_and_shows_it():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await pilot.click('#new-session')
        await pilot.pause()
        assert tab_labels(tui) == ['Session 1', 'Session 2', '+']
        assert tui.active_key == 'session-2'
        assert pane_of(tui, 'session-2').display is True
        assert pane_of(tui, 'session-1').display is False
        assert tabs_of(tui).active != 'new-session'
        assert tui.query_one(ChatInput).has_focus


async def test_switching_tabs_swaps_the_pane_content():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        submit(tui, 'first question')
        await pilot.pause(0.1)
        await pilot.click('#new-session')
        await pilot.pause()
        submit(tui, 'second question')
        await pilot.pause(0.1)
        await pilot.click('#tab-session-1')
        await pilot.pause()
        assert tui.active_key == 'session-1'
        assert 'first question' in rendered(pane_of(tui, 'session-1'))
        assert 'second question' not in rendered(pane_of(tui, 'session-1'))
        assert 'second question' in rendered(pane_of(tui, 'session-2'))
        assert pane_of(tui, 'session-2').display is False


async def test_a_background_session_is_rendered_once_its_tab_is_selected():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await pilot.click('#new-session')
        await pilot.pause()
        await pilot.click('#tab-session-1')
        await pilot.pause()
        tui.bind_session('session-2', 'uuid-2')
        tui.append_agent_delta('late output', agent_id='Angel Holiday:uuid-2')
        assert rendered(pane_of(tui, 'session-2')) == ''
        assert 'late output' in sections_of(pane_of(tui, 'session-2'))
        await pilot.click('#tab-session-2')
        await pilot.pause(0.3)
        assert tui.active_key == 'session-2'
        assert 'late output' in rendered(pane_of(tui, 'session-2'))


async def test_two_sessions_stream_at_the_same_time():
    tui = AgentTUI()
    bridges = Bridges(delay=5.0)
    tui.set_session_factory(bridges)
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        submit(tui, 'slow one')
        await pilot.pause(0.1)
        await pilot.click('#new-session')
        await pilot.pause()
        submit(tui, 'slow two')
        await pilot.pause(0.1)
        assert bridges.by_key['session-1'].chats == ['slow one']
        assert bridges.by_key['session-2'].chats == ['slow two']
        first, second = tui._sessions['session-1'], tui._sessions['session-2']
        assert (first.busy, second.busy) == (True, True)
        assert first.worker is not None and first.worker.is_running is True
        assert second.worker is not None and second.worker.is_running is True
        assert tabs_of(tui).get_tab('tab-session-1').has_class('-busy')
        assert tabs_of(tui).get_tab('tab-session-2').has_class('-busy')
        tui.cancel_chat('session-1')
        tui.cancel_chat('session-2')
        await pilot.pause(0.1)
        assert (first.busy, second.busy) == (False, False)
        assert not tabs_of(tui).get_tab('tab-session-1').has_class('-busy')
        assert not tabs_of(tui).get_tab('tab-session-2').has_class('-busy')


async def test_a_busy_session_only_blocks_its_own_tab():
    tui = AgentTUI()
    bridges = Bridges(delay=5.0)
    tui.set_session_factory(bridges)
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        submit(tui, 'slow one')
        await pilot.pause(0.1)
        submit(tui, 'ignored')
        await pilot.pause(0.1)
        assert bridges.by_key['session-1'].chats == ['slow one']
        await pilot.click('#new-session')
        await pilot.pause()
        submit(tui, 'slow two')
        await pilot.pause(0.1)
        assert bridges.by_key['session-2'].chats == ['slow two']


async def test_each_session_keeps_its_own_draft():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        chat = tui.query_one(ChatInput)
        chat.text = 'draft one'
        await pilot.click('#new-session')
        await pilot.pause()
        assert chat.text == ''
        chat.text = 'draft two'
        await pilot.click('#tab-session-1')
        await pilot.pause()
        assert chat.text == 'draft one'
        await pilot.click('#tab-session-2')
        await pilot.pause()
        assert chat.text == 'draft two'


async def test_commands_go_to_the_session_that_typed_them():
    tui = AgentTUI()
    bridges = Bridges(delay=5.0, reply='Stopped')
    tui.set_session_factory(bridges)
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        submit(tui, 'slow one')
        await pilot.pause(0.1)
        await pilot.click('#new-session')
        await pilot.pause()
        submit(tui, '/stop')
        await pilot.pause(0.1)
        assert bridges.by_key['session-2'].commands == ['/stop']
        assert bridges.by_key['session-1'].commands == []
        assert tui._sessions['session-1'].busy is True
        assert 'Stopped' in sections_of(pane_of(tui, 'session-2'))


async def test_session_titles_land_on_the_tab_and_the_header():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        tui.set_session_title('session-1', 'renamed')
        assert tab_labels(tui) == ['renamed', '+']
        assert tui.query_one(HeaderBar).session_title == 'renamed'
        await pilot.click('#new-session')
        await pilot.pause()
        assert tui.query_one(HeaderBar).session_title == ''
        tui.set_session_title('session-1', 'background')
        assert tab_labels(tui) == ['background', 'Session 2', '+']
        assert tui.query_one(HeaderBar).session_title == ''
        tui.set_session_title('missing', 'ignored')
        assert tab_labels(tui) == ['background', 'Session 2', '+']


async def test_events_are_routed_to_the_session_that_owns_them():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await pilot.click('#new-session')
        await pilot.pause()
        tui.bind_session('session-1', 'uuid-1')
        tui.bind_session('session-2', 'uuid-2')
        tui.append_agent_delta('for one', agent_id='Angel Holiday:uuid-1')
        tui.append_agent_delta('for two', agent_id='Angel Holiday:uuid-2')
        tui.append_agent_delta('subagent of one', agent_id='sub-uuid', path=('Angel Holiday:uuid-1',))
        tui.append_tool_call('bash', '{"cmd": "ls"}', agent_id='Angel Holiday:uuid-1')
        assert 'for two' in sections_of(pane_of(tui, 'session-2'))
        assert 'for one' not in sections_of(pane_of(tui, 'session-2'))
        assert 'for one' in sections_of(pane_of(tui, 'session-1'))
        assert 'subagent of one' in sections_of(pane_of(tui, 'session-1'))
        blocks = pane_of(tui, 'session-1')._blocks
        assert [block.kind for block in blocks] == ['agent', 'agent', 'tools']
        assert [block.agent for block in blocks[:2]] == ['Angel Holiday', 'sub-uuid']


async def test_events_of_an_unknown_session_are_dropped():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        tui.append_agent_delta('stray', agent_id='Angel Holiday:nowhere')
        tui.append_error('stray error', agent_id='Angel Holiday:nowhere')
        assert sections_of(pane_of(tui, 'session-1')) == ''


async def test_a_plan_belongs_to_its_session():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        popup = tui.query_one(PopupSelector)
        tui.bind_session('session-1', 'uuid-1')
        tui.show_plan([PLAN_ITEM], agent_id='Angel Holiday:uuid-1')
        assert popup.display is True
        assert 'do the thing' in popup.render()
        await pilot.click('#new-session')
        await pilot.pause()
        assert popup.display is False
        tui.show_plan([PLAN_ITEM], agent_id='Angel Holiday:uuid-1')
        assert popup.display is False
        await pilot.click('#tab-session-1')
        await pilot.pause()
        assert popup.display is True
        assert 'do the thing' in popup.render()


async def test_clearing_a_session_resets_its_pane_title_and_plan():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        tui.bind_session('session-1', 'uuid-1')
        tui.append_system('notice')
        tui.set_session_title('session-1', 'renamed')
        tui.show_plan([PLAN_ITEM], agent_id='Angel Holiday:uuid-1')
        tui.clear_session('session-1')
        assert pane_of(tui, 'session-1')._blocks == []
        assert tab_labels(tui) == ['Session 1', '+']
        assert tui.query_one(HeaderBar).session_title == ''
        assert tui.query_one(PopupSelector).display is False
        assert tui.session_key('Angel Holiday:uuid-1') is None
        assert tui._sessions['session-1'].plan == []
        tui.clear_session('missing')


async def test_clear_messages_only_empties_the_session_on_screen():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await pilot.click('#new-session')
        await pilot.pause()
        tui.append_system('on the second tab', key='session-2')
        await pilot.click('#tab-session-1')
        await pilot.pause()
        tui.append_system('on the first tab', key='session-1')
        tui.clear_messages()
        assert sections_of(pane_of(tui, 'session-1')) == ''
        assert 'on the second tab' in sections_of(pane_of(tui, 'session-2'))


async def test_tool_keys_reach_every_pane():
    tui = AgentTUI()
    tui.set_tools([StubTool('bash', 'cmd')])
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await pilot.click('#new-session')
        await pilot.pause()
        assert pane_of(tui, 'session-1')._tool_keys == {'bash': 'cmd'}
        assert pane_of(tui, 'session-2')._tool_keys == {'bash': 'cmd'}


async def test_a_restored_session_is_the_first_tab():
    tui = AgentTUI()
    tui.open_sessions([('uuid-1', 'stored title', [UserMessage('old question')])])
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        assert tab_labels(tui) == ['stored title', '+']
        assert 'old question' in rendered(pane_of(tui, 'session-1'))
        assert tui.query_one(HeaderBar).session_title == 'stored title'
        assert tui.session_key('Angel Holiday:uuid-1') == 'session-1'


async def test_a_restored_session_reuses_its_id_when_chatting():
    tui = AgentTUI()
    sessions: list[str | None] = []
    bridge = Bridge()

    def factory(key: str, session_id: str | None) -> Bridge:
        sessions.append(session_id)
        return bridge

    tui.set_session_factory(factory)
    tui.open_sessions([('uuid-1', 'stored title', [])])
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        assert sessions == ['uuid-1']
        assert tui._sessions['session-1'].session_id == 'uuid-1'


async def test_open_sessions_names_the_tab_from_stored_messages():
    tui = AgentTUI()
    history: Sequence[UserMessage] = [UserMessage('hi')]
    tui.open_sessions([('uuid-1', '', list(history))])
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        assert tab_labels(tui) == ['Session 1', '+']
        assert isinstance(pane_of(tui, 'session-1')._blocks[0].sections[0].text, str)


async def test_every_stored_session_becomes_a_tab():
    tui = AgentTUI()
    tui.open_sessions([('uuid-1', 'first', [UserMessage('question one')]), ('uuid-2', 'second', [UserMessage('question two')])])
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        assert tab_labels(tui) == ['first', 'second', '+']
        assert 'question one' in rendered(pane_of(tui, 'session-1'))
        assert 'question two' in sections_of(pane_of(tui, 'session-2'))
        assert tui.session_key('Angel Holiday:uuid-2') == 'session-2'


async def test_the_first_stored_session_is_the_one_on_screen():
    tui = AgentTUI()
    tui.open_sessions([('uuid-1', 'first', [UserMessage('question one')]), ('uuid-2', 'second', [])])
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        assert tui.active_key == 'session-1'
        assert pane_of(tui, 'session-1').display is True
        assert pane_of(tui, 'session-2').display is False
        assert tabs_of(tui).active == 'tab-session-1'
        assert tui.query_one(HeaderBar).session_title == 'first'
        assert tui.query_one(ChatInput).has_focus is True


async def test_nothing_to_restore_opens_a_fresh_session():
    tui = AgentTUI()
    tui.open_sessions([])
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        assert tab_labels(tui) == ['Session 1', '+']
        assert tui.active_key == 'session-1'


async def test_stored_sessions_added_while_running_show_the_first_one():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await pilot.click('#new-session')
        await pilot.pause()
        tui.open_sessions([('uuid-1', 'first', []), ('uuid-2', 'second', [])])
        await pilot.pause()
        assert tab_labels(tui) == ['Session 1', 'Session 2', 'first', 'second', '+']
        assert tui.active_key == 'session-3'
        assert pane_of(tui, 'session-3').display is True


async def test_a_session_transcript_survives_a_tab_switch():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        tui.append_system('kept', key='session-1')
        await pilot.click('#new-session')
        await pilot.pause()
        await pilot.click('#tab-session-1')
        await pilot.pause()
        assert 'kept' in sections_of(pane_of(tui, 'session-1'))
        assert 'kept' not in sections_of(pane_of(tui, 'session-2'))


async def test_closing_a_session_removes_its_tab_and_pane():
    tui = AgentTUI()
    bridges = Bridges()
    tui.set_session_factory(bridges)
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await pilot.click('#new-session')
        await pilot.pause()
        tui.append_system('on the second tab', key='session-2')
        await close_and_confirm(tui, pilot, 'session-2')
        assert tab_labels(tui) == ['Session 1', '+']
        assert tui.session_pane('session-2') is None
        assert bridges.by_key['session-2'].closes == 1
        assert bridges.by_key['session-1'].closes == 0
        assert 'on the second tab' not in sections_of(pane_of(tui, 'session-1'))


async def test_closing_the_active_session_shows_the_next_one():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await pilot.click('#new-session')
        await pilot.click('#new-session')
        await pilot.pause()
        assert tui.active_key == 'session-3'
        await pilot.click('#tab-session-2')
        await pilot.pause()
        await close_and_confirm(tui, pilot, 'session-2')
        assert tui.active_key == 'session-3'
        assert pane_of(tui, 'session-3').display is True
        assert tab_labels(tui) == ['Session 1', 'Session 3', '+']
        assert tabs_of(tui).active == 'tab-session-3'
        assert tabs_of(tui).active_tab is not None
        assert tabs_of(tui).active_tab.has_class('-active')


async def test_closing_the_last_session_shows_the_previous_one():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await pilot.click('#new-session')
        await pilot.pause()
        await close_and_confirm(tui, pilot, 'session-2')
        assert tui.active_key == 'session-1'
        assert pane_of(tui, 'session-1').display is True
        assert tui.query_one(ChatInput).has_focus
        assert tabs_of(tui).active == 'tab-session-1'


async def test_closing_a_background_session_keeps_the_one_on_screen():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await pilot.click('#new-session')
        await pilot.click('#tab-session-1')
        await pilot.pause()
        assert tui.active_key == 'session-1'
        await close_and_confirm(tui, pilot, 'session-2')
        assert tui.active_key == 'session-1'
        assert tab_labels(tui) == ['Session 1', '+']


async def test_the_last_remaining_session_cannot_be_closed():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        tui.close_session('session-1')
        await pilot.pause()
        assert not isinstance(tui.screen, YesNoDialog)
        assert tab_labels(tui) == ['Session 1', '+']
        assert tui.session_pane('session-1') is not None
        assert tui.active_key == 'session-1'


async def test_closing_drops_the_session_routing_and_plan():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await pilot.click('#new-session')
        await pilot.pause()
        tui.bind_session('session-2', 'uuid-2')
        tui.show_plan([PLAN_ITEM], agent_id='Angel Holiday:uuid-2')
        assert tui.session_key('Angel Holiday:uuid-2') == 'session-2'
        await close_and_confirm(tui, pilot, 'session-2')
        assert tui.session_key('Angel Holiday:uuid-2') is None
        tui.append_agent_delta('late output', agent_id='Angel Holiday:uuid-2')
        assert 'late output' not in sections_of(pane_of(tui, 'session-1'))
        assert tui.query_one(PopupSelector).display is False


async def test_closing_cancels_a_running_chat():
    tui = AgentTUI()
    bridges = Bridges(delay=5.0)
    tui.set_session_factory(bridges)
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        submit(tui, 'slow one')
        await pilot.pause(0.1)
        await pilot.click('#new-session')
        await pilot.pause()
        worker = tui._sessions['session-1'].worker
        assert worker is not None and worker.is_running is True
        await close_and_confirm(tui, pilot, 'session-1')
        assert worker.is_running is False
        assert bridges.by_key['session-1'].closes == 1
        assert tab_labels(tui) == ['Session 2', '+']
        assert tui.active_key == 'session-2'


async def test_closing_a_session_that_never_chatted_only_drops_its_tab():
    tui = AgentTUI()
    bridges = Bridges()
    tui.set_session_factory(bridges)
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await pilot.click('#new-session')
        await pilot.pause()
        await close_and_confirm(tui, pilot, 'session-2')
        assert bridges.by_key['session-2'].chats == []
        assert bridges.by_key['session-2'].closes == 1
        assert tui._keys_by_uuid == {}


async def test_ctrl_w_deletes_a_word_instead_of_closing_the_session():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await pilot.click('#new-session')
        await pilot.pause()
        chat = tui.query_one(ChatInput)
        chat.text = 'hello world'
        chat.cursor_location = (0, len('hello world'))
        await pilot.press('ctrl+w')
        await pilot.pause()
        assert chat.text == 'hello '
        assert tab_labels(tui) == ['Session 1', 'Session 2', '+']


async def test_a_tab_click_hands_the_input_back_its_focus():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await pilot.click('#new-session')
        await pilot.pause()
        chat = tui.query_one(ChatInput)
        await pilot.click('#tab-session-1')
        await pilot.pause()
        assert chat.has_focus is True
        await pilot.click('#tab-session-1')
        await pilot.pause()
        assert chat.has_focus is True
        await pilot.press('h')
        await pilot.pause()
        assert chat.text == 'h'


async def test_closing_a_background_tab_hands_the_input_back_its_focus():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await pilot.click('#new-session')
        await pilot.pause()
        tabs = tabs_of(tui)
        await pilot.click('#tab-session-1', offset=(tabs.get_tab('tab-session-1').size.width - len(CLOSE_MARK) + 1, 0))
        await pilot.pause()
        await pilot.click('#yes')
        await pilot.pause()
        assert tab_labels(tui) == ['Session 2', '+']
        assert tui.active_key == 'session-2'
        await pilot.press('h')
        await pilot.pause()
        assert tui.query_one(ChatInput).text == 'h'


async def test_a_refused_close_hands_the_input_back_its_focus():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        tabs = tabs_of(tui)
        tab = tabs.get_tab('tab-session-1')
        await pilot.click('#tab-session-1', offset=(tab.size.width - len(CLOSE_MARK) + 1, 0))
        await pilot.pause()
        assert tab_labels(tui) == ['Session 1', '+']
        assert tui.query_one(ChatInput).has_focus is True


async def test_the_close_command_closes_the_session():
    tui = AgentTUI()
    bridges = Bridges()
    tui.set_session_factory(bridges)
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await pilot.click('#new-session')
        await pilot.pause()
        submit(tui, '/close')
        await pilot.pause()
        await pilot.click('#yes')
        await pilot.pause()
        assert bridges.by_key['session-2'].commands == []
        assert tab_labels(tui) == ['Session 1', '+']


async def test_the_close_command_keeps_the_last_session():
    tui = AgentTUI()
    bridges = Bridges()
    tui.set_session_factory(bridges)
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        submit(tui, '/close')
        await pilot.pause(0.1)
        assert tab_labels(tui) == ['Session 1', '+']
        assert tui.pane is not None
        assert sections_of(pane_of(tui, 'session-1')) == ''


async def test_the_close_command_ignores_trailing_arguments():
    tui = AgentTUI()
    bridges = Bridges()
    tui.set_session_factory(bridges)
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await pilot.click('#new-session')
        await pilot.pause()
        submit(tui, '/close now')
        await pilot.pause()
        await pilot.click('#yes')
        await pilot.pause()
        assert tab_labels(tui) == ['Session 1', '+']


async def test_a_message_merely_starting_with_close_is_not_a_close():
    tui = AgentTUI()
    bridges = Bridges(reply='Unknown command: /closer')
    tui.set_session_factory(bridges)
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await pilot.click('#new-session')
        await pilot.pause()
        submit(tui, '/closer look')
        await pilot.pause(0.1)
        assert bridges.by_key['session-2'].commands == ['/closer look']
        assert tab_labels(tui) == ['Session 1', 'Session 2', '+']


async def test_clicking_a_tabs_close_mark_asks_before_closing():
    tui = AgentTUI()
    bridges = Bridges()
    tui.set_session_factory(bridges)
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await pilot.click('#new-session')
        await pilot.click('#tab-session-1')
        await pilot.pause()
        tabs = tabs_of(tui)
        tab = tabs.get_tab('tab-session-2')
        padding = 1
        await pilot.click('#tab-session-2', offset=(tab.size.width - len(CLOSE_MARK) + padding, 0))
        await pilot.pause()
        assert tab_labels(tui) == ['Session 1', 'Session 2', '+']
        assert bridges.by_key['session-2'].closes == 0
        await pilot.click('#yes')
        await pilot.pause()
        assert tab_labels(tui) == ['Session 1', '+']
        assert tui.active_key == 'session-1'
        assert bridges.by_key['session-2'].closes == 1


async def test_closing_is_refused_while_a_picker_is_open():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await pilot.click('#new-session')
        await pilot.pause()
        picker = pilot.app.run_worker(tui.pick([('one', '1')], title='Pick'))
        await pilot.pause()
        tui.close_session('session-2')
        await pilot.pause()
        assert tab_labels(tui) == ['Session 1', 'Session 2', '+']
        assert len(tui._sessions) == 2
        await pilot.press('escape')
        assert await picker.wait() is None


async def test_closing_an_unknown_session_does_nothing():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        tui.close_session('missing')
        await pilot.pause()
        assert tab_labels(tui) == ['Session 1', '+']


async def test_a_cancelled_close_keeps_the_session():
    tui = AgentTUI()
    bridges = Bridges()
    tui.set_session_factory(bridges)
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await pilot.click('#new-session')
        await pilot.pause()
        tui.close_session('session-2')
        await pilot.pause()
        assert isinstance(tui.screen, YesNoDialog)
        await pilot.click('#no')
        await pilot.pause()
        assert tab_labels(tui) == ['Session 1', 'Session 2', '+']
        assert bridges.by_key['session-2'].closes == 0
        assert tui.active_key == 'session-2'
        assert tui.query_one(ChatInput).has_focus is True


async def test_escape_cancels_the_close_dialog():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await pilot.click('#new-session')
        await pilot.pause()
        tui.close_session('session-2')
        await pilot.pause()
        await pilot.press('escape')
        await pilot.pause()
        assert tab_labels(tui) == ['Session 1', 'Session 2', '+']
        assert not isinstance(tui.screen, YesNoDialog)
        assert tui.query_one(ChatInput).has_focus is True


async def test_the_close_dialog_names_the_session():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await pilot.click('#new-session')
        await pilot.pause()
        tui.set_session_title('session-2', 'the named one')
        tui.close_session('session-2')
        await pilot.pause()
        assert 'the named one' in str(tui.screen.query_one(Label).render())
        await pilot.press('escape')
        await pilot.pause()


async def test_a_second_close_request_does_not_stack_dialogs():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await pilot.click('#new-session')
        await pilot.click('#new-session')
        await pilot.pause()
        tui.close_session('session-2')
        await pilot.pause()
        tui.close_session('session-3')
        await pilot.pause()
        assert len([screen for screen in tui.screen_stack if isinstance(screen, YesNoDialog)]) == 1
        await pilot.press('escape')
        await pilot.pause()
        assert tab_labels(tui) == ['Session 1', 'Session 2', 'Session 3', '+']


async def test_the_new_command_adds_a_session():
    tui = AgentTUI()
    bridges = Bridges()
    tui.set_session_factory(bridges)
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        submit(tui, 'first')
        await pilot.pause(0.1)
        submit(tui, '/new')
        await pilot.pause()
        assert tab_labels(tui) == ['Session 1', 'Session 2', '+']
        assert tui.active_key == 'session-2'
        assert bridges.by_key['session-2'].commands == []
        assert pane_of(tui, 'session-1').display is False
        assert tui.query_one(ChatInput).text == ''
        assert tui.query_one(ChatInput).has_focus is True


async def test_the_new_command_ignores_trailing_arguments():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        submit(tui, '/new now')
        await pilot.pause()
        assert tab_labels(tui) == ['Session 1', 'Session 2', '+']


async def test_a_message_merely_starting_with_new_is_not_a_new_session():
    tui = AgentTUI()
    bridges = Bridges()
    tui.set_session_factory(bridges)
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        submit(tui, 'a /newer look')
        await pilot.pause(0.1)
        assert tab_labels(tui) == ['Session 1', '+']
        assert bridges.by_key['session-1'].chats == ['a /newer look']


def content_offset(pane: MessagePane, x: int, y: int) -> tuple[int, int]:
    base = pane.content_region.offset - pane.region.offset
    return (base.x + x, base.y + y)


async def test_tabs_still_take_clicks_after_clicking_a_pane_that_is_streaming():
    """A click in a live pane must not keep the mouse: the tab strip needs it back."""
    tui = AgentTUI()
    bridges = Bridges(delay=5.0)
    tui.set_session_factory(bridges)
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        submit(tui, 'slow one')
        await pilot.pause(0.1)
        await pilot.click('#new-session')
        await pilot.pause()
        await pilot.click('#tab-session-1')
        await pilot.pause()
        pane = pane_of(tui, 'session-1')
        tui.append_agent_delta('streaming along', key='session-1')
        await pilot.mouse_down('#pane-session-1', offset=content_offset(pane, 2, 1))
        # The stream re-renders the block while the button is still down.
        tui.append_agent_delta(' and on', key='session-1')
        pane._flush_now()
        await pilot.mouse_up('#pane-session-1', offset=content_offset(pane, 2, 1))
        await pilot.pause()
        assert tui.app.mouse_captured is None
        await pilot.click('#tab-session-2')
        await pilot.pause()
        assert tui.active_key == 'session-2'
        tui.cancel_chat('session-1')


async def test_tabs_still_take_clicks_after_clicking_a_panes_border():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await pilot.click('#new-session')
        await pilot.pause()
        await pilot.click('#tab-session-1')
        await pilot.pause()
        tui.append_system('something to look at', key='session-1')
        # (3, 0) is on the pane's top border, not on its text.
        await pilot.click('#pane-session-1', offset=(3, 0))
        await pilot.pause()
        assert tui.app.mouse_captured is None
        await pilot.click('#tab-session-2')
        await pilot.pause()
        assert tui.active_key == 'session-2'
