import asyncio
from pathlib import Path

from rqark_app.agent.manager import AgentManager
from rqark_app.app import AgentApp, Message
from rqark_app.config.manager import ConfigManager
from rqark_app.session.manager import SessionManager
from rqark_app.session.storage import CloudStorage, JSONLStorage
from rqark_app.types.event import ProviderSwitch
from rqark_core.types.chat import Chunk, ToolMessage, UserMessage
from rqark_core.types.event import AgentPayload
from rqark_core.types.tool import PlanItem

from rqark_tui.tui import AgentTUI, Restored
from rqark_tui.tui.event_handler import EventHandler


async def restored_sessions(config_mgr: ConfigManager, session_mgr: SessionManager) -> list[Restored]:
    """The sessions this directory remembers, most recently used first.

    A remembered session whose transcript is gone (cleared or closed by another
    run) is forgotten instead of being restored.
    """
    restored: list[Restored] = []
    for session_id in config_mgr.dir_cache.get_session_ids(config_mgr.cwd_hash):
        session = await session_mgr.get(session_id)
        if session is None:
            config_mgr.dir_cache.remove_session_id(config_mgr.cwd_hash, session_id)
            continue
        restored.append((session.uuid, session.title, session.get_last_chunk()))
    return restored


def load_agent_manager(config_mgr: ConfigManager) -> AgentManager:
    """Agents the user configured in ``~/.rqark/agents/*.yml``.

    The built-in presets in ``rqark_app.config.default`` only seed that directory on
    first run; once it holds files, the files win.
    """
    return AgentManager(config_mgr.agents)


def _is_subagent(ev: AgentPayload) -> bool:
    return bool(ev.path)


async def connect_agent_event_to_tui(app: AgentApp, tui: AgentTUI):
    @app.on_think()
    async def think(ev: AgentPayload[Chunk]) -> None:
        if _is_subagent(ev):
            return
        tui.append_think_delta(str(ev.payload.content), agent_id=ev.agent_id, path=ev.path)

    @app.on_content()
    async def content(ev: AgentPayload[Chunk]) -> None:
        if _is_subagent(ev):
            return
        tui.append_agent_delta(str(ev.payload.content), agent_id=ev.agent_id, path=ev.path)

    @app.on_tool_calls()
    async def tool_calls(ev: AgentPayload[Chunk]) -> None:
        if _is_subagent(ev):
            return
        if isinstance(ev.payload.content, list):
            for call in ev.payload.content:
                tui.append_tool_call(call.name, call.arguments, agent_id=ev.agent_id, path=ev.path)

    @app.on_tool_result()
    async def tool_result(ev: AgentPayload[ToolMessage]) -> None:
        if _is_subagent(ev):
            return
        tm = ev.payload
        if not isinstance(tm, ToolMessage):
            tm = tm.content if isinstance(getattr(tm, 'content', None), ToolMessage) else None
        if tm is not None:
            tui.append_tool_result(tm.tool_name or '', tm.content, agent_id=ev.agent_id, path=ev.path)

    @app.on_error()
    async def error(ev: AgentPayload[Chunk]) -> None:
        if _is_subagent(ev):
            return
        tui.append_error(str(ev.payload.content), agent_id=ev.agent_id, path=ev.path)

    @app.on_message()
    async def message(ev: AgentPayload[Message]) -> None:
        if _is_subagent(ev):
            return
        if isinstance(ev.payload, UserMessage):
            tui.set_user_message_id(ev.payload.id, ev.agent_id, ev.path)
        tui.close_agent_message(ev.agent_id, ev.path)

    @app.on_plan()
    async def plan(ev: AgentPayload[list[PlanItem]]) -> None:
        if _is_subagent(ev) or ':' not in ev.agent_id:
            return
        tui.show_plan(ev.payload, ev.agent_id, ev.path)

    @app.on_provider_switched()
    async def provider_switched(ev: AgentPayload[ProviderSwitch]) -> None:
        tui.set_model_name(ev.payload.new.model_name)


async def _main() -> None:
    config_mgr = ConfigManager(str(Path.home() / '.rqark'))
    await config_mgr.load()
    agent_mgr = load_agent_manager(config_mgr)

    if config_mgr.cloud_client is not None:
        storage = CloudStorage(config_mgr.cloud_client, source='TUI')
    else:
        storage = JSONLStorage(config_mgr.config_path / 'sessions' / 'tui')

    app = AgentApp(config_mgr.providers, storage)
    await app.session_mgr.load()

    tui = AgentTUI()
    tui.set_cloud_mode(config_mgr.cloud_client is not None)
    tui.set_agent_name(agent_mgr.agent.name)
    tui.set_model_name(app.provider_mgr.provider.name)
    tui.set_tools(agent_mgr.agent.tools)
    tui.set_session_factory(lambda key, session_id: EventHandler(app, tui, agent_mgr, config_mgr, session_id, key))

    await connect_agent_event_to_tui(app, tui)

    tui.open_sessions(await restored_sessions(config_mgr, app.session_mgr))
    await tui.run()


def main():
    asyncio.run(_main())


if __name__ == '__main__':
    main()
