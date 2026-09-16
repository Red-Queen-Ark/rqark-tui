import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import cast

from rqark_app.agent.manager import AgentManager
from rqark_app.app import AgentApp
from rqark_app.config.manager import ConfigManager
from rqark_app.provider.manager import ProviderManager
from rqark_app.types.session import Session
from rqark_core.types.chat import AssistantMessage, Chunk, UserMessage
from rqark_core.types.event import AgentPayload
from rqark_core.types.provider import Provider

from rqark_tui.tui import AgentTUI
from rqark_tui.tui.components.popup import Entry
from rqark_tui.tui.event_handler import EventHandler


def make_providers() -> list[Provider]:
    return [
        Provider('model-a', 'key-a', 'https://a.example', 0),
        Provider('model-b', 'key-b', 'https://b.example', 1),
        Provider('model-c', 'key-c', 'https://c.example', 2),
    ]


@dataclass
class FakeChunk:
    content: str


@dataclass
class FakePayload:
    payload: FakeChunk


@dataclass
class FakeTitled:
    title: str


class FakeSessionManager:
    def __init__(self) -> None:
        self.sessions: dict[str, Session] = {}
        self.saved: list[str] = []
        self.deleted: list[str] = []
        self.created = 0

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


class FakeChatHelper:
    def __init__(self, title: str = 'generated title') -> None:
        self.title = title
        self.calls: list[tuple[str, str]] = []

    async def gen_title(self, session_uuid: str, first_message: str) -> FakeTitled:
        self.calls.append((session_uuid, first_message))
        return FakeTitled(self.title)


class FakeDirCache:
    def __init__(self) -> None:
        self.stored: list[tuple[str, str]] = []

    def set_session_id(self, cwd_hash: str, session_id: str) -> None:
        self.stored.append((cwd_hash, session_id))


class FakeConfigManager:
    def __init__(self) -> None:
        self.cwd_hash = 'cwd-hash'
        self.dir_cache = FakeDirCache()


class StubAgent:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeTUI:
    def __init__(self, pick_result: Entry | None = None) -> None:
        self.pick_result = pick_result
        self.picked: list[dict] = []
        self.session_titles: list[str] = []
        self.model_names: list[str] = []
        self.agent_names: list[str] = []
        self.cancel_count = 0
        self.clear_count = 0

    def set_session_title(self, title: str) -> None:
        self.session_titles.append(title)

    def set_model_name(self, name: str) -> None:
        self.model_names.append(name)

    def set_agent_name(self, name: str) -> None:
        self.agent_names.append(name)

    def cancel_chat(self) -> None:
        self.cancel_count += 1

    def clear_messages(self) -> None:
        self.clear_count += 1

    async def pick(self, entries, *, title: str = '', index: int = 0) -> Entry | None:
        self.picked.append({'entries': list(entries), 'title': title, 'index': index})
        return self.pick_result


class FakeApp:
    def __init__(self) -> None:
        self.session_mgr = FakeSessionManager()
        self.provider_mgr = ProviderManager(make_providers())
        self.chat_helper = FakeChatHelper()
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

    async def emit_think(self, text: str) -> None:
        handler = cast('object', self.handlers['think'])
        await cast('object', handler)(cast(AgentPayload[Chunk], FakePayload(FakeChunk(text))))

    async def emit_content(self, text: str) -> None:
        handler = self.handlers['content']
        await handler(cast(AgentPayload[Chunk], FakePayload(FakeChunk(text))))

    async def chat(self, text: str, agent, session_id: str | None = None) -> Session:
        self.chat_calls.append({'text': text, 'agent': agent, 'session_id': session_id})
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


def build(
    session_id: str | None = None,
    pick_result: Entry | None = None,
    agents: tuple[str, ...] = ('agent-a', 'agent-b'),
) -> tuple[EventHandler, FakeApp, FakeTUI, FakeConfigManager, AgentManager]:
    app = FakeApp()
    tui = FakeTUI(pick_result)
    agent_mgr = AgentManager(cast('object', [StubAgent(name) for name in agents]))
    config_mgr = FakeConfigManager()
    handler = EventHandler(
        cast(AgentApp, app),
        cast(AgentTUI, tui),
        agent_mgr,
        cast(ConfigManager, config_mgr),
        session_id,
    )
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
    assert tui.session_titles == ['generated title']


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
    assert tui.session_titles == ['generated title']


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
    assert tui.cancel_count == 1
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
    assert tui.cancel_count == 1


async def test_clear_deletes_the_session_and_resets_the_tui():
    handler, app, tui, _config, _agents = build()
    session = await app.session_mgr.create()
    handler.session_id = session.uuid
    assert await handler.command('/clear') == 'Conversation cleared'
    assert app.session_mgr.deleted == [session.uuid]
    assert handler.session_id is None
    assert tui.clear_count == 1
    assert tui.cancel_count == 1
    assert tui.session_titles == ['']


async def test_clear_without_a_session_still_resets_the_tui():
    handler, app, tui, _config, _agents = build()
    assert await handler.command('/clear') == 'Conversation cleared'
    assert app.session_mgr.deleted == []
    assert tui.clear_count == 1


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
