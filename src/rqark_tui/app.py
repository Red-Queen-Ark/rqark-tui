import asyncio
from pathlib import Path

import httpx
from rqark_app.agent.manager import AgentManager
from rqark_app.app import AgentApp
from rqark_app.config.manager import ConfigManager
from rqark_app.session.manager import SessionManager
from rqark_app.session.storage import CloudStorage, JSONLStorage
from rqark_app.sop.types import Sop
from rqark_app.types.event import ProviderSwitch
from rqark_core.types.chat import Chunk, Message, ToolMessage, UserMessage
from rqark_core.types.event import AgentPayload
from rqark_core.types.tool import PlanItem

from rqark_tui.tui import AgentTUI, Restored
from rqark_tui.tui.event_handler import EventHandler

SESSION_SOURCE = 'TUI'


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
        restored.append((session.uuid, session.title, session.get_last_chunk(), session.agent_id))
    return restored


def load_agent_manager(config_mgr: ConfigManager) -> AgentManager:
    """Agents the user configured in ``~/.rqark/agents/*.yml``, or the cloud catalogue.

    The built-in presets in ``rqark_app.config.default`` only seed that directory on
    first run; once it holds files, the files win. The default agent the cloud holds
    for this app's source starts out selected.
    """
    return AgentManager(config_mgr.agents, config_mgr.default_agent)


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


def build_storage(config_mgr: ConfigManager) -> CloudStorage | JSONLStorage:
    """Where this run keeps its transcripts: the data cloud when configured, else local files."""
    if config_mgr.cloud_client is not None:
        return CloudStorage(config_mgr.cloud_client, source=SESSION_SOURCE)
    return JSONLStorage(config_mgr.config_path / 'sessions' / SESSION_SOURCE.lower())


def build_app(config_mgr: ConfigManager) -> AgentApp:
    """The agent app for this run, with the storage its transcripts live in."""
    return AgentApp(config_mgr.providers, build_storage(config_mgr))


async def load_workspace(config_mgr: ConfigManager, app: AgentApp) -> tuple[list[Restored], list[Sop]]:
    """Read the stored sessions and the SOP list together.

    Both are independent round trips to storage, so they run at the same time
    rather than one after the other.
    """
    _, sops = await asyncio.gather(app.session_mgr.load(), config_mgr.sop_manager.list())
    return await restored_sessions(config_mgr, app.session_mgr), list(sops)


class Startup:
    """What the background start holds on to, so the run can drain it afterwards."""

    def __init__(self) -> None:
        self.config_mgr: ConfigManager | None = None
        self.app: AgentApp | None = None


async def bootstrap(tui: AgentTUI, startup: Startup, config_dir: Path | None = None, cloud_transport: httpx.AsyncBaseTransport | None = None) -> tuple[list[Restored], list[Sop]]:
    """Read the config, build the agent app and load the workspace, in the background.

    Every step here answers a cloud round trip, so it runs after the interface
    is on screen: the header, the input and the tab strip are painted first and
    fill in as each answer arrives.
    """
    config_mgr = ConfigManager(str(config_dir or Path.home() / '.rqark'), cloud_transport=cloud_transport, source=SESSION_SOURCE)
    await config_mgr.load()
    agent_mgr = load_agent_manager(config_mgr)
    app = build_app(config_mgr)
    startup.config_mgr, startup.app = config_mgr, app

    tui.set_cloud_mode(config_mgr.cloud_client is not None)
    tui.set_agent_name(agent_mgr.agent.name)
    tui.set_model_name(app.provider_mgr.provider.name)
    tui.set_tools(agent_mgr.agent.tools)
    tui.set_session_factory(lambda key, session_id: EventHandler(app, tui, agent_mgr, config_mgr, session_id, key))
    await connect_agent_event_to_tui(app, tui)

    return await load_workspace(config_mgr, app)


async def _main() -> None:
    startup = Startup()
    tui = AgentTUI()
    tui.load_startup(lambda: bootstrap(tui, startup))
    await tui.run()
    if startup.app is not None:
        await startup.app.drain_memory_writes()


def main():
    asyncio.run(_main())


if __name__ == '__main__':
    main()
