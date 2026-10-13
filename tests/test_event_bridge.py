from rqark_app.types.event import ProviderSwitch
from rqark_core.types.chat import AssistantMessage, Chunk, ToolCall, ToolMessage, UserMessage
from rqark_core.types.event import AgentPayload
from rqark_core.types.provider import Provider
from rqark_core.types.tool import PlanItem

from rqark_tui.app import connect_agent_event_to_tui

ROOT = 'agent:uuid'
SUBAGENT = 'sub-uuid'
PATH = (ROOT,)
NESTED = (ROOT, SUBAGENT)


class FakeApp:
    def __init__(self) -> None:
        self.handlers: dict = {}

    def _register(self, name):
        def register(fn):
            self.handlers[name] = fn
            return fn

        return register

    def on_think(self):
        return self._register('think')

    def on_content(self):
        return self._register('content')

    def on_tool_calls(self):
        return self._register('tool_calls')

    def on_tool_result(self):
        return self._register('tool_result')

    def on_error(self):
        return self._register('error')

    def on_message(self):
        return self._register('message')

    def on_plan(self):
        return self._register('plan')

    def on_provider_switched(self):
        return self._register('provider_switched')


class FakeTui:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))

        return record


async def bridge() -> tuple[FakeApp, FakeTui]:
    app = FakeApp()
    tui = FakeTui()
    await connect_agent_event_to_tui(app, tui)
    return app, tui


async def test_subagent_chunks_never_reach_the_tui():
    app, tui = await bridge()

    await app.handlers['think'](AgentPayload(SUBAGENT, PATH, Chunk('reasoning_content', 'hmm')))
    await app.handlers['content'](AgentPayload(SUBAGENT, PATH, Chunk('content', 'working on it')))
    await app.handlers['tool_calls'](AgentPayload(SUBAGENT, PATH, Chunk('tool_calls', [ToolCall('c1', 'function', 'read_file', '{}')])))
    await app.handlers['tool_result'](AgentPayload(SUBAGENT, PATH, ToolMessage('c1', 'file contents', 'read_file')))
    await app.handlers['error'](AgentPayload(SUBAGENT, PATH, Chunk('error', 'boom')))

    assert tui.calls == []


async def test_subagent_messages_never_reach_the_tui():
    app, tui = await bridge()

    await app.handlers['message'](AgentPayload(SUBAGENT, PATH, AssistantMessage('found it')))
    await app.handlers['message'](AgentPayload(SUBAGENT, PATH, UserMessage('go')))

    assert tui.calls == []


async def test_nested_subagent_events_never_reach_the_tui():
    app, tui = await bridge()

    await app.handlers['content'](AgentPayload(SUBAGENT, NESTED, Chunk('content', 'deeper')))
    await app.handlers['message'](AgentPayload(SUBAGENT, NESTED, AssistantMessage('done')))

    assert tui.calls == []


async def test_subagent_plans_never_reach_the_tui():
    app, tui = await bridge()

    await app.handlers['plan'](AgentPayload(SUBAGENT, PATH, [PlanItem(id='1', content='do the thing', status='pending')]))

    assert tui.calls == []


async def test_main_agent_chunks_reach_the_tui():
    app, tui = await bridge()

    await app.handlers['think'](AgentPayload(ROOT, (), Chunk('reasoning_content', 'hmm')))
    await app.handlers['content'](AgentPayload(ROOT, (), Chunk('content', 'working on it')))
    await app.handlers['tool_calls'](AgentPayload(ROOT, (), Chunk('tool_calls', [ToolCall('c1', 'function', 'read_file', '{}')])))
    await app.handlers['tool_result'](AgentPayload(ROOT, (), ToolMessage('c1', 'file contents', 'read_file')))
    await app.handlers['error'](AgentPayload(ROOT, (), Chunk('error', 'boom')))

    assert [name for name, _, _ in tui.calls] == ['append_think_delta', 'append_agent_delta', 'append_tool_call', 'append_tool_result', 'append_error']


async def test_main_agent_messages_reach_the_tui():
    app, tui = await bridge()

    await app.handlers['message'](AgentPayload(ROOT, (), UserMessage('go')))
    await app.handlers['message'](AgentPayload(ROOT, (), AssistantMessage('done')))

    assert [name for name, _, _ in tui.calls] == ['set_user_message_id', 'close_agent_message', 'close_agent_message']


async def test_main_agent_plan_reaches_the_tui():
    app, tui = await bridge()

    await app.handlers['plan'](AgentPayload(ROOT, (), [PlanItem(id='1', content='do the thing', status='pending')]))

    assert [name for name, _, _ in tui.calls] == ['show_plan']


async def test_provider_switched_reaches_the_tui():
    app, tui = await bridge()

    await app.handlers['provider_switched'](AgentPayload(ROOT, (), ProviderSwitch(Provider('model', 'key', 'https://example', 0), Provider('other', 'key', 'https://example', 0))))

    assert [name for name, _, _ in tui.calls] == ['set_model_name']
