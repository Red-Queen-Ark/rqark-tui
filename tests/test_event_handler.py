import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import cast

from rqark_app.agent.manager import AgentManager
from rqark_app.app import AgentApp
from rqark_app.config.manager import ConfigManager
from rqark_app.provider.manager import ProviderManager
from rqark_app.types.session import Session, SummaryMessage
from rqark_core.types.chat import AssistantMessage, Chunk, Message, ToolMessage, UserMessage
from rqark_core.types.event import AgentPayload
from rqark_core.types.provider import Provider

from rqark_tui.tui import AgentTUI
from rqark_tui.tui.components.popup import Entry
from rqark_tui.tui.event_handler import EventHandler


def make_providers() -> list[Provider]:
    return [Provider('model-a', 'key-a', 'https://a.example', 0), Provider('model-b', 'key-b', 'https://b.example', 1), Provider('model-c', 'key-c', 'https://c.example', 2)]


@dataclass
class FakeChunk:
    content: str


@dataclass
class FakePayload:
    payload: FakeChunk
    agent_id: str = ''
    path: tuple[str, ...] = ()


@dataclass
class FakeTitled:
    title: str


class FakeSessionManager:
    def __init__(self) -> None:
        self.sessions: dict[str, Session] = {}
        self.saved: list[str] = []
        self.deleted: list[str] = []
        self.created = 0
        self.reverted: list[tuple[str, str]] = []

    async def create(self) -> Session:
        self.created += 1
        session = Session()
        self.sessions[session.uuid] = session
        return session

    async def get(self, uuid: str) -> Session | None:
        return self.sessions.get(uuid)

    async def save(self, uuid: str) -> None:
        self.saved.append(uuid)

    async def delete(self, uuid: str) -> None:
        self.deleted.append(uuid)
        self.sessions.pop(uuid, None)

    async def revert(self, session_id: str, message_id: str) -> Session | None:
        self.reverted.append((session_id, message_id))
        session = self.sessions.get(session_id)
        if session is None or session.revert_to(message_id) is None:
            return None
        await self.save(session_id)
        return session


class FakeChatHelper:
    def __init__(self, title: str = 'generated title') -> None:
        self.title = title
        self.calls: list[tuple[str, str]] = []

    async def gen_title(self, session_uuid: str, first_message: str) -> FakeTitled:
        self.calls.append((session_uuid, first_message))
        return FakeTitled(self.title)


class FakeCompactor:
    def __init__(self, summary: SummaryMessage | None = None) -> None:
        self.summary = summary
        self.calls: list[list[Message]] = []

    async def get_summary(self, messages: list[Message]) -> SummaryMessage | None:
        self.calls.append(list(messages))
        return self.summary


class FakeDirCache:
    def __init__(self) -> None:
        self.stored: list[tuple[str, str]] = []
        self.forgotten: list[tuple[str, str]] = []

    def set_session_id(self, cwd_hash: str, session_id: str) -> None:
        self.stored.append((cwd_hash, session_id))

    def remove_session_id(self, cwd_hash: str, session_id: str) -> None:
        self.forgotten.append((cwd_hash, session_id))


class FakeConfigManager:
    def __init__(self) -> None:
        self.cwd_hash = 'cwd-hash'
        self.dir_cache = FakeDirCache()


class StubAgent:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeTUI:
    def __init__(self, pick_result: Entry | None = None, key: str = 'session-1') -> None:
        self.pick_result = pick_result
        self.picked: list[dict] = []
        self.session_titles: list[tuple[str, str]] = []
        self.model_names: list[str] = []
        self.agent_names: list[str] = []
        self.cancelled: list[str | None] = []
        self.cleared: list[str] = []
        self.replayed: list[tuple[str, list[object]]] = []
        self.statuses: list[tuple[str, str]] = []
        self.status_hidden: list[str] = []
        self.bound: list[tuple[str, str]] = []
        self.key = key

    def set_session_title(self, key: str, title: str) -> None:
        self.session_titles.append((key, title))

    def set_model_name(self, name: str) -> None:
        self.model_names.append(name)

    def set_agent_name(self, name: str) -> None:
        self.agent_names.append(name)

    def cancel_chat(self, key: str | None = None) -> None:
        self.cancelled.append(key)

    def clear_session(self, key: str) -> None:
        self.cleared.append(key)

    def replay_session(self, key: str, messages) -> None:
        self.replayed.append((key, list(messages)))

    def show_status(self, key: str, text: str) -> None:
        self.statuses.append((key, text))

    def hide_status(self, key: str) -> None:
        self.status_hidden.append(key)

    def bind_session(self, key: str, session_id: str) -> None:
        self.bound.append((key, session_id))

    def session_key(self, agent_id: str = '', path: tuple[str, ...] = ()) -> str | None:
        return self.key

    async def pick(self, entries, *, title: str = '', index: int = 0) -> Entry | None:
        self.picked.append({'entries': list(entries), 'title': title, 'index': index})
        return self.pick_result


class FakeApp:
    def __init__(self) -> None:
        self.session_mgr = FakeSessionManager()
        self.provider_mgr = ProviderManager(make_providers())
        self.chat_helper = FakeChatHelper()
        self.compactor = FakeCompactor()
        self.handlers: dict[str, object] = {}
        self.chat_calls: list[dict] = []
        self.stream_content = ''
        self.stream_reasoning = ''
        self.chat_error: BaseException | None = None
        self.during_chat: Callable[[], Awaitable[None]] | None = None
        self.session: Session | None = None

    def on_think(self):
        return self._register('think')

    def on_content(self):
        return self._register('content')

    def _register(self, name: str):
        def decorator(handler):
            self.handlers[name] = handler
            return handler

        return decorator

    async def emit_think(self, text: str, path: tuple[str, ...] = ()) -> None:
        handler = cast('object', self.handlers['think'])
        await cast('object', handler)(cast(AgentPayload[Chunk], FakePayload(FakeChunk(text), 'agent-a:session-1', path)))

    async def emit_content(self, text: str, path: tuple[str, ...] = ()) -> None:
        handler = self.handlers['content']
        await handler(cast(AgentPayload[Chunk], FakePayload(FakeChunk(text), 'agent-a:session-1', path)))

    async def chat(self, text: str, agent, session_id: str | None = None, images: list[str] | None = None) -> Session:
        self.chat_calls.append({'text': text, 'agent': agent, 'session_id': session_id, 'images': images})
        session = await self.session_mgr.get(session_id) if session_id is not None else None
        if session is None:
            session = await self.session_mgr.create()
        self.session = session
        if self.stream_reasoning:
            await self.emit_think(self.stream_reasoning)
        if self.stream_content:
            await self.emit_content(self.stream_content)
        if self.during_chat is not None:
            await self.during_chat()
        if self.chat_error is not None:
            raise self.chat_error
        return session


def build(session_id: str | None = None, pick_result: Entry | None = None, agents: tuple[str, ...] = ('agent-a', 'agent-b'), key: str = 'session-1') -> tuple[EventHandler, FakeApp, FakeTUI, FakeConfigManager, AgentManager]:
    app = FakeApp()
    tui = FakeTUI(pick_result, key)
    agent_mgr = AgentManager(cast('object', [StubAgent(name) for name in agents]))
    config_mgr = FakeConfigManager()
    handler = EventHandler(cast(AgentApp, app), cast(AgentTUI, tui), agent_mgr, cast(ConfigManager, config_mgr), session_id, key)
    return handler, app, tui, config_mgr, agent_mgr


async def test_stream_tracking_handlers_are_registered():
    _handler, app, _tui, _config, _agents = build()
    assert set(app.handlers) == {'think', 'content'}


async def test_chat_creates_a_session_when_none_is_set():
    handler, app, _tui, _config, _agents = build()
    app.session = None
    await handler.chat('hello')
    assert app.session_mgr.created == 1
    assert handler.session_id == app.session.uuid
    assert app.chat_calls[0]['session_id'] == app.session.uuid


async def test_chat_binds_the_session_to_its_tab():
    handler, app, tui, _config, _agents = build()
    await handler.chat('hello')
    assert tui.bound == [('session-1', app.session.uuid)]


async def test_stream_events_of_another_session_are_ignored():
    handler, app, tui, _config, _agents = build(key='session-1')
    tui.key = 'session-2'
    app.stream_content = 'other session'
    app.stream_reasoning = 'other reasoning'
    await handler.chat('hello')
    assert handler._stream_content == ''
    assert handler._stream_reasoning == ''


async def test_subagent_events_are_not_part_of_the_session_stream():
    handler, app, _tui, _config, _agents = build()

    async def subagent_output() -> None:
        await app.emit_content('subagent answer', path=('agent-a:session-1',))

    app.during_chat = subagent_output
    app.stream_content = 'main answer'
    await handler.chat('hello')
    assert handler._stream_content == 'main answer'


async def test_chat_reuses_an_existing_session():
    handler, app, _tui, _config, _agents = build()
    session = await app.session_mgr.create()
    handler.session_id = session.uuid
    await handler.chat('hello')
    assert app.session_mgr.created == 1
    assert app.chat_calls[0]['session_id'] == session.uuid


async def test_chat_stores_the_session_id_for_the_working_directory():
    handler, app, _tui, config, _agents = build()
    await handler.chat('hello')
    assert config.dir_cache.stored == [('cwd-hash', app.session.uuid)]


async def test_chat_passes_the_current_agent():
    handler, app, _tui, _config, agent_mgr = build()
    await handler.chat('hello')
    assert app.chat_calls[0]['agent'] is agent_mgr.agent


async def test_streamed_content_and_reasoning_are_accumulated():
    handler, app, _tui, _config, _agents = build()
    app.stream_content = 'the answer'
    app.stream_reasoning = 'the reasoning'
    await handler.chat('hello')
    assert handler._stream_content == 'the answer'
    assert handler._stream_reasoning == 'the reasoning'
    assert handler._stream_active is False


async def test_stream_events_outside_a_chat_are_ignored():
    handler, app, _tui, _config, _agents = build()
    await app.emit_content('stray chunk')
    await app.emit_think('stray thought')
    assert handler._stream_content == ''
    assert handler._stream_reasoning == ''


async def test_chat_starts_with_an_empty_stream_buffer():
    handler, app, _tui, _config, _agents = build()
    app.stream_content = 'first'
    await handler.chat('one')
    app.stream_content = 'second'
    await handler.chat('two')
    assert handler._stream_content == 'second'


async def test_title_is_generated_once_for_an_untitled_session():
    handler, app, tui, _config, _agents = build()
    await handler.chat('hello')
    await asyncio.gather(*handler._title_tasks)
    assert app.chat_helper.calls == [(app.session.uuid, 'hello')]
    assert tui.session_titles == [('session-1', 'generated title')]


async def test_title_is_not_generated_for_a_titled_session():
    handler, app, tui, _config, _agents = build()
    session = await app.session_mgr.create()
    session.title = 'already named'
    app.session = session
    handler.session_id = session.uuid
    await handler.chat('hello')
    assert handler._title_tasks == set()
    assert tui.session_titles == []


async def test_empty_generated_title_is_not_applied():
    handler, app, tui, _config, _agents = build()
    app.chat_helper.title = ''
    await handler.chat('hello')
    await asyncio.gather(*handler._title_tasks)
    assert tui.session_titles == []


async def test_gen_title_updates_the_header():
    handler, app, tui, _config, _agents = build()
    await handler.gen_title('uuid', 'first message')
    assert app.chat_helper.calls == [('uuid', 'first message')]
    assert tui.session_titles == [('session-1', 'generated title')]


async def test_cancellation_without_a_stop_request_propagates():
    handler, app, _tui, _config, _agents = build()
    app.chat_error = asyncio.CancelledError()
    try:
        await handler.chat('hello')
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError('the cancellation should propagate')
    assert handler._stream_active is False


async def stop_during_chat(handler, app) -> None:
    async def during() -> None:
        await handler.command('/stop')

    app.during_chat = during
    app.chat_error = asyncio.CancelledError()


async def test_stop_saves_the_partial_answer():
    handler, app, tui, _config, _agents = build()
    session = await app.session_mgr.create()
    handler.session_id = session.uuid
    app.stream_content = 'partial answer'
    app.stream_reasoning = 'partial reasoning'
    await stop_during_chat(handler, app)
    await handler.chat('hello')
    assert tui.cancelled == ['session-1']
    assert [type(message) for message in session.history] == [UserMessage, AssistantMessage]
    assert session.history[0].content == 'hello'
    partial = session.history[1]
    assert isinstance(partial, AssistantMessage)
    assert (partial.content, partial.reasoning_content) == ('partial answer', 'partial reasoning')
    assert app.session_mgr.saved == [session.uuid]


async def test_partial_save_extends_the_existing_chunk():
    handler, app, _tui, _config, _agents = build()
    session = await app.session_mgr.create()
    session.history = [AssistantMessage(content='earlier answer')]
    handler.session_id = session.uuid
    app.stream_content = 'partial answer'
    await stop_during_chat(handler, app)
    await handler.chat('continued')
    assert isinstance(session.history[0], AssistantMessage)
    assert session.history[0].content == 'earlier answer'
    assert [type(message) for message in session.history[1:]] == [UserMessage, AssistantMessage]
    assert session.history[2].content == 'partial answer'


async def test_stop_records_reasoning_even_without_content():
    handler, app, _tui, _config, _agents = build()
    session = await app.session_mgr.create()
    handler.session_id = session.uuid
    app.stream_reasoning = 'only reasoning'
    await stop_during_chat(handler, app)
    await handler.chat('hello')
    partial = session.history[-1]
    assert isinstance(partial, AssistantMessage)
    assert (partial.content, partial.reasoning_content) == ('', 'only reasoning')


async def test_stop_without_streamed_text_saves_nothing():
    handler, app, _tui, _config, _agents = build()
    session = await app.session_mgr.create()
    handler.session_id = session.uuid
    await stop_during_chat(handler, app)
    await handler.chat('hello')
    assert app.session_mgr.saved == []
    assert session.history == []


async def test_partial_save_without_a_session_saves_nothing():
    handler, app, _tui, _config, _agents = build()
    handler._stream_content = 'text'
    handler._last_chat_text = 'hello'
    assert handler.session_id is None
    await handler._save_partial()
    assert app.session_mgr.saved == []


async def test_partial_save_with_a_missing_session_saves_nothing():
    handler, app, _tui, _config, _agents = build(session_id='missing')
    handler._stream_content = 'text'
    await handler._save_partial()
    assert app.session_mgr.saved == []


async def test_stop_marks_the_request_and_cancels_the_worker():
    handler, _app, tui, _config, _agents = build()
    assert await handler.command('/stop') == 'Stopped'
    assert handler._stop_requested is True
    assert tui.cancelled == ['session-1']


async def test_clear_deletes_the_session_and_resets_the_tui():
    handler, app, tui, _config, _agents = build()
    session = await app.session_mgr.create()
    handler.session_id = session.uuid
    assert await handler.command('/clear') == 'Conversation cleared'
    assert app.session_mgr.deleted == [session.uuid]
    assert handler.session_id is None
    assert tui.cleared == ['session-1']
    assert tui.cancelled == ['session-1']


async def test_clear_without_a_session_still_resets_the_tui():
    handler, app, tui, _config, _agents = build()
    assert await handler.command('/clear') == 'Conversation cleared'
    assert app.session_mgr.deleted == []
    assert tui.cleared == ['session-1']


async def test_models_lists_every_provider_with_escaped_labels():
    handler, app, tui, _config, _agents = build(pick_result=('label', '2'))
    app.provider_mgr.providers[1].name = '[bold]model-b[/bold]'
    app.provider_mgr.cur_index = 1
    assert await handler.command('/models') == 'Model: [bold]model-b[/bold] -> model-c'
    picked = tui.picked[0]
    assert picked['title'] == 'Models'
    assert picked['index'] == 1
    assert picked['entries'][0] == ('[b]model-a[/b] https://a.example', '0')
    assert picked['entries'][1] == (r'[b]\[bold]model-b\[/bold][/b] https://b.example', '1')
    assert tui.model_names == ['model-c']


async def test_models_without_a_selection_returns_none():
    handler, _app, tui, _config, _agents = build(pick_result=None)
    assert await handler.command('/models') is None
    assert tui.model_names == []


async def test_models_without_providers_reports_it():
    handler, app, tui, _config, _agents = build()
    app.provider_mgr.providers = []
    assert await handler.command('/models') == 'No models available'
    assert tui.picked == []


async def test_models_ignores_trailing_arguments():
    handler, _app, tui, _config, _agents = build(pick_result=('label', '1'))
    assert await handler.command('/models now') == 'Model: model-a -> model-b'
    assert tui.model_names == ['model-b']


async def test_agents_lists_every_agent():
    handler, _app, tui, _config, agent_mgr = build(pick_result=('label', '1'))
    assert await handler.command('/agents') == 'Agent: agent-a -> agent-b'
    picked = tui.picked[0]
    assert picked['title'] == 'Agents'
    assert picked['index'] == 0
    assert agent_mgr.cur_index == 1
    assert picked['entries'] == [('[b]agent-a[/b]', '0'), ('[b]agent-b[/b]', '1')]
    assert tui.agent_names == ['agent-b']


async def test_agents_without_a_selection_returns_none():
    handler, _app, tui, _config, _agents = build(pick_result=None)
    assert await handler.command('/agents') is None
    assert tui.agent_names == []


async def test_agents_without_any_agent_reports_it():
    handler, _app, tui, _config, _agents = build(agents=())
    assert await handler.command('/agents') == 'No agents available'
    assert tui.picked == []


async def test_unknown_command_reports_the_name():
    handler, _app, _tui, _config, _agents = build()
    assert await handler.command('/nope') == 'Unknown command: /nope'


async def test_unknown_command_keeps_the_session():
    handler, app, _tui, _config, _agents = build()
    session = await app.session_mgr.create()
    handler.session_id = session.uuid
    await handler.command('/nope')
    assert handler.session_id == session.uuid
    assert app.session_mgr.deleted == []


async def test_command_name_without_arguments_still_matches():
    handler, _app, tui, _config, _agents = build(pick_result=('label', '0'))
    assert await handler.command('/models   ') == 'Model: model-a -> model-a'
    assert tui.model_names == ['model-a']


async def test_chat_forwards_the_attached_images():
    handler, app, _tui, _config, _agents = build()
    images = ['data:image/png;base64,AAAA']
    await handler.chat('look at this', images)
    assert app.chat_calls[0]['images'] == images


async def test_chat_without_images_forwards_none():
    handler, app, _tui, _config, _agents = build()
    await handler.chat('hello')
    assert app.chat_calls[0]['images'] is None


async def test_stop_saves_the_partial_answer_with_its_images():
    handler, app, _tui, _config, _agents = build()
    session = await app.session_mgr.create()
    handler.session_id = session.uuid
    app.stream_content = 'partial answer'
    images = ['data:image/png;base64,AAAA']
    await stop_during_chat(handler, app)
    await handler.chat('look', images)
    saved_user = session.history[0]
    assert isinstance(saved_user, UserMessage)
    assert saved_user.images == images


async def test_no_title_is_generated_for_an_image_only_message():
    handler, app, tui, _config, _agents = build()
    await handler.chat('', ['data:image/png;base64,AAAA'])
    await asyncio.gather(*handler._title_tasks)
    assert app.chat_helper.calls == []
    assert tui.session_titles == []


async def test_clear_forgets_the_session_in_the_dir_cache():
    handler, app, _tui, config, _agents = build()
    session = await app.session_mgr.create()
    handler.session_id = session.uuid
    assert await handler.command('/clear') == 'Conversation cleared'
    assert config.dir_cache.forgotten == [('cwd-hash', session.uuid)]
    assert handler.session_id is None


async def test_closing_a_session_forgets_it_in_the_dir_cache():
    handler, app, _tui, config, _agents = build()
    session = await app.session_mgr.create()
    handler.session_id = session.uuid
    await handler.close()
    assert app.session_mgr.deleted == [session.uuid]
    assert config.dir_cache.forgotten == [('cwd-hash', session.uuid)]
    assert handler.session_id is None


async def test_closing_without_a_session_forgets_nothing():
    handler, _app, _tui, config, _agents = build()
    await handler.close()
    assert config.dir_cache.forgotten == []


async def test_revert_drops_the_target_user_message_and_everything_after_it():
    handler, app, _tui, _config, _agents = build()
    session = await app.session_mgr.create()
    handler.session_id = session.uuid
    first = UserMessage('first')
    session.history = [first, AssistantMessage('answer'), UserMessage('second')]
    reverted = await handler.revert(first.id)
    assert reverted is session
    assert app.session_mgr.reverted == [(session.uuid, first.id)]
    assert session.history == []
    assert app.session_mgr.saved == [session.uuid]


async def test_revert_returns_none_when_the_message_is_not_a_user_turn():
    handler, app, _tui, _config, _agents = build()
    session = await app.session_mgr.create()
    handler.session_id = session.uuid
    first = UserMessage('first')
    answer = AssistantMessage('answer')
    session.history = [first, answer, UserMessage('second')]
    assert await handler.revert(answer.id) is None


async def test_revert_keeps_the_user_turns_before_the_target():
    handler, app, _tui, _config, _agents = build()
    session = await app.session_mgr.create()
    handler.session_id = session.uuid
    first, second = UserMessage('first'), UserMessage('second')
    answer = AssistantMessage('answer')
    session.history = [first, answer, second]
    reverted = await handler.revert(second.id)
    assert reverted is session
    assert session.history == [first, answer]


async def test_revert_without_a_session_returns_none():
    handler, app, _tui, _config, _agents = build()
    assert await handler.revert('m1') is None
    assert app.session_mgr.reverted == []


async def test_compact_summarises_the_last_chunk_and_saves_it():
    handler, app, _tui, _config, _agents = build()
    session = await app.session_mgr.create()
    handler.session_id = session.uuid
    first, answer = UserMessage('first'), AssistantMessage('answer')
    session.history = [first, answer]
    app.compactor.summary = SummaryMessage('the summary')
    assert await handler.command('/compact') == 'Conversation compacted'
    assert app.compactor.calls == [[first, answer]]
    assert session.history == [first, answer, app.compactor.summary]
    assert session.get_last_chunk() == [app.compactor.summary]
    assert app.session_mgr.saved == [session.uuid]
    assert _tui.replayed == [('session-1', [app.compactor.summary])]


async def test_compact_tells_the_user_it_is_working():
    handler, app, _tui, _config, _agents = build()
    session = await app.session_mgr.create()
    handler.session_id = session.uuid
    session.history = [UserMessage('first'), AssistantMessage('answer')]
    app.compactor.summary = SummaryMessage('the summary')
    assert await handler.command('/compact') == 'Conversation compacted'
    assert _tui.statuses == [('session-1', 'Compacting…')]
    assert _tui.status_hidden == ['session-1']


async def test_compact_drops_the_status_line_when_the_summary_fails():
    handler, app, _tui, _config, _agents = build()
    session = await app.session_mgr.create()
    handler.session_id = session.uuid
    session.history = [UserMessage('first'), AssistantMessage('answer')]
    app.compactor.summary = None
    assert await handler.command('/compact') == 'Compaction failed, the conversation is unchanged'
    assert _tui.statuses == [('session-1', 'Compacting…')]
    assert _tui.status_hidden == ['session-1']


async def test_compact_reports_a_failure_without_touching_the_session():
    handler, app, _tui, _config, _agents = build()
    session = await app.session_mgr.create()
    handler.session_id = session.uuid
    first, answer = UserMessage('first'), AssistantMessage('answer')
    session.history = [first, answer]
    app.compactor.summary = None
    assert await handler.command('/compact') == 'Compaction failed, the conversation is unchanged'
    assert app.compactor.calls == [[first, answer]]
    assert session.history == [first, answer]
    assert app.session_mgr.saved == []
    assert _tui.replayed == []


async def test_compact_skips_the_compactor_when_there_is_nothing_to_summarise():
    handler, app, _tui, _config, _agents = build()
    session = await app.session_mgr.create()
    handler.session_id = session.uuid
    session.history = [ToolMessage(tool_call_id='1', content='tool output', tool_name='bash')]
    app.compactor.summary = SummaryMessage('unused')
    assert await handler.command('/compact') == 'Nothing to compact'
    assert app.compactor.calls == []
    assert _tui.statuses == []
    assert app.session_mgr.saved == []


async def test_compact_reports_nothing_without_a_history():
    handler, app, _tui, _config, _agents = build()
    session = await app.session_mgr.create()
    handler.session_id = session.uuid
    app.compactor.summary = SummaryMessage('unused')
    assert await handler.command('/compact') == 'Nothing to compact'
    assert app.compactor.calls == []
    assert _tui.replayed == []


async def test_compact_without_a_session_reports_nothing():
    handler, app, _tui, _config, _agents = build()
    assert await handler.command('/compact') == 'Nothing to compact'
    assert app.compactor.calls == []


async def test_compact_with_a_missing_session_reports_nothing():
    handler, app, _tui, _config, _agents = build(session_id='missing')
    assert await handler.command('/compact') == 'Nothing to compact'
    assert app.compactor.calls == []
