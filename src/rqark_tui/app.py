import asyncio

from rqark_app.agent.manager import AgentManager
from rqark_app.app import AgentApp, Message, PlanItem
from rqark_app.session.storage import JSONLStorage
from rqark_core.types.event import AgentPayload
from rqark_core.types.chat import Chunk, ToolMessage
from rqark_app.types.event import ProviderSwitch
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
        tui.append_tool_result(ev.payload.tool_name or '', ev.payload.content)

    @app.on_error()
    async def error(ev: AgentPayload[Chunk]) -> None:
        tui.append_error(str(ev.payload.content))

    @app.on_message()
    async def message(ev: AgentPayload[Message]) -> None:
        tui.close_agent_message()

    @app.on_plan()
    async def plan(ev: AgentPayload[list[PlanItem]]) -> None:
        tui.set_plan(ev.payload)

    @app.on_provider_switched()
    async def provider_switched(ev: AgentPayload[ProviderSwitch]) -> None:
        tui.set_model_name(ev.payload.new.model_name)
    
async def _main() -> None:
    config_mgr = ConfigManager('./.rqark')
    config_mgr.load()
    
    agent_mgr = AgentManager(AGENTS)

    storage = JSONLStorage(config_mgr.config_path / 'sessions')
    app = AgentApp(config_mgr.providers, storage)
    await app.session_mgr.load()

    tui = AgentTUI()
    await connect_agent_event_to_tui(app, tui)
    tui.set_agent_name(agent_mgr.agent.name)
    tui.set_model_name(app.provider_mgr.provider.name)
    await tui.run()


def main():
    asyncio.run(_main())
