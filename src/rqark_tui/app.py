import asyncio

from rqark_app.agent.manager import AgentManager
from rqark_app.app import AgentApp, Message
from rqark_app.session.storage import JSONLStorage
from rqark_app.types.event import ProviderSwitch
from rqark_core.types.chat import Chunk, ToolMessage
from rqark_core.types.event import AgentPayload

from rqark_tui.config.default import AGENTS
from rqark_tui.config.manager import ConfigManager
from rqark_tui.tui import AgentTUI


async def connect_agent_event_to_tui(app: AgentApp, tui: AgentTUI):
    @app.on_think()
    async def think(ev: AgentPayload[Chunk]) -> None:
        tui.append_think_delta(str(ev.payload.content))

    @app.on_content()
    async def content(ev: AgentPayload[Chunk]) -> None:
        tui.append_agent_delta(str(ev.payload.content))

    @app.on_tool_calls()
    async def tool_calls(ev: AgentPayload[Chunk]) -> None:
        if isinstance(ev.payload.content, list):
            for call in ev.payload.content:
                tui.append_tool_call(call.name, call.arguments)

    @app.on_tool_result()
    async def tool_result(ev: AgentPayload[ToolMessage]) -> None:
        tm = ev.payload
        if not isinstance(tm, ToolMessage):
            tm = tm.content if isinstance(getattr(tm, 'content', None), ToolMessage) else None
        if tm is not None:
            tui.append_tool_result(tm.tool_name or '', tm.content)

    @app.on_error()
    async def error(ev: AgentPayload[Chunk]) -> None:
        tui.append_error(str(ev.payload.content))

    @app.on_message()
    async def message(ev: AgentPayload[Message]) -> None:
        tui.close_agent_message()

    @app.on_provider_switched()
    async def provider_switched(ev: AgentPayload[ProviderSwitch]) -> None:
        tui.set_model_name(ev.payload.new.model_name)

async def _main() -> None:
    config_mgr = ConfigManager('./.rqark')
    config_mgr.load()
    session_id = config_mgr.dir_cache.get_session_id(config_mgr.cwd_hash)
    agent_mgr = AgentManager(AGENTS)

    storage = JSONLStorage(config_mgr.config_path / 'sessions')
    app = AgentApp(config_mgr.providers, storage)
    await app.session_mgr.load()

    tui = AgentTUI()
    await connect_agent_event_to_tui(app, tui)
    tui.set_agent_name(agent_mgr.agent.name)
    tui.set_model_name(app.provider_mgr.provider.name)
    tui.set_tools(agent_mgr.agent.tools)

    title_tasks: set[asyncio.Task] = set()

    async def gen_title(session_uuid: str, first_message: str) -> None:
        titled = await app.chat_helper.gen_title(session_uuid, first_message)
        if titled is not None and titled.title:
            tui.set_session_title(titled.title)

    async def chat_handler(text: str) -> None:
        nonlocal session_id
        session = await app.chat(text, agent_mgr.agent, session_id=session_id)
        session_id = session.uuid
        config_mgr.dir_cache.set_session_id(config_mgr.cwd_hash, session_id)
        if not session.title:
            task = asyncio.create_task(gen_title(session.uuid, text))
            title_tasks.add(task)
            task.add_done_callback(title_tasks.discard)

    tui.set_chat_handler(chat_handler)
    session = await app.session_mgr.get(session_id) if session_id is not None else None
    if session is not None:
        tui.set_session_title(session.title)
        tui.restore_session(session.get_last_chunk())
    await tui.run()


def main():
    asyncio.run(_main())
