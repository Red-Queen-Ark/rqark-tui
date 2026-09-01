import asyncio
from pathlib import Path

from rqark_app.agent.agents import AgentHoliday, Diana, Wednesday
from rqark_app.app import AgentApp, Provider
from rqark_app.provider.manager import ProviderManager
from rqark_app.session.storage import JSONLStorage
from rqark_app.types.agent import BaseAgent
from rqark_app.types.event import ProviderSwitch
from rqark_core.types.chat import Chunk, Message, ToolMessage
from rqark_core.types.event import AgentPayload
from rqark_core.types.tool import PlanItem

from rqark_tui.libs.dir_cache import DirCache
from rqark_tui.tui import AgentTUI
from rqark_tui.tui.commands import COMMANDS


def main() -> None:
    asyncio.run(_main())


def _resolve_provider_index(provider_mgr: ProviderManager, arg: str) -> int | None:
    if arg.isdigit():
        index = int(arg)
        return index if 0 <= index < len(provider_mgr.providers) else None
    for index, provider in enumerate(provider_mgr.providers):
        if provider.model_name == arg:
            return index
    return None


async def _main() -> None:
    providers = [
        Provider(
            'gemma4:e4b-mlx',
            '-',
            'http://127.0.0.1:11434/v1',
            -1,
            combine=True,
            thinking='disabled',
        ),
    ]
    app = AgentApp(providers, JSONLStorage(Path.home() / '.rqark' / 'sessions'))
    try:
        await app.session_mgr.load()
    except Exception:
        pass
    agents: dict[str, BaseAgent] = {
        'Wednesday': Wednesday(),
        'Diana': Diana(),
        'AngelHoliday': AgentHoliday(),
    }
    agent: BaseAgent = agents['Wednesday']
    tui = AgentTUI()
    cache = DirCache()
    cwd_hash = DirCache.compute_hash(Path.cwd())
    session_id = cache.get_session_id(cwd_hash)
    title_tasks: set[asyncio.Task] = set()

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

    async def gen_title(session_uuid: str, first_message: str) -> None:
        titled = await app.chat_helper.gen_title(session_uuid, first_message)
        if titled is not None and titled.title:
            tui.set_session_title(titled.title)

    async def chat_handler(text: str) -> None:
        nonlocal session_id
        session = await app.chat(text, agent, session_id=session_id)
        session_id = session.uuid
        cache.set_session_id(cwd_hash, session_id)
        if not session.title:
            task = asyncio.create_task(gen_title(session.uuid, text))
            title_tasks.add(task)
            task.add_done_callback(title_tasks.discard)

    async def command_handler(command: str) -> str | None:
        nonlocal session_id, agent
        name, _, arg = command.partition(' ')
        arg = arg.strip()
        match name:
            case '/help':
                return '\n'.join(f'{c}  {d}' for c, d in COMMANDS)
            case '/new':
                tui.cancel_chat()
                session_id = None
                tui.clear_messages()
                tui.set_session_title('')
                return 'New conversation started'
            case '/clear':
                tui.cancel_chat()
                if session_id is not None:
                    await app.session_mgr.delete(session_id)
                    session_id = None
                tui.clear_messages()
                tui.set_session_title('')
                return 'Conversation cleared'
            case '/stop':
                tui.cancel_chat()
                return 'Stopped'
            case '/models':
                if arg:
                    index = _resolve_provider_index(app.provider_mgr, arg)
                    if index is None:
                        return f'Unknown model: {arg}'
                    app.provider_mgr.switch_to(index)
                    tui.set_model_name(app.provider_mgr.provider.model_name)
                    return f'Model: {app.provider_mgr.provider.model_name}'
                return '\n'.join(f'{i}: {p.model_name}' for i, p in enumerate(app.provider_mgr.providers))
            case '/agents':
                if arg:
                    next_agent = agents.get(arg)
                    if next_agent is None:
                        return f'Unknown agent: {arg}'
                    agent = next_agent
                    tui.set_agent_name(agent.name)
                    return f'Agent: {agent.name}'
                return '\n'.join(agents)
            case _:
                return f'Unknown command: {name} (try /help)'

    tui.set_agent_name(agent.name)
    tui.set_model_name(app.provider_mgr.provider.model_name)
    tui.set_command_handler(command_handler)
    if session_id is not None:
        session = await app.session_mgr.get(session_id)
        if session is not None:
            if session.title:
                tui.set_session_title(session.title)
            if session.plan_items:
                tui.set_plan(session.plan_items)
    tui.set_chat_handler(chat_handler)
    await tui.run_async()


if __name__ == '__main__':
    main()
