import asyncio
from pathlib import Path

from rqark_app.agent.agents import Wednesday
from rqark_app.app import AgentApp, Provider
from rqark_app.session.storage import JSONLStorage
from rqark_app.types.event import ProviderSwitch
from rqark_core.types.chat import Chunk, Message, ToolMessage
from rqark_core.types.event import AgentPayload

from rqark_tui.libs.dir_cache import DirCache
from rqark_tui.tui import AgentTUI


def main() -> None:
    asyncio.run(_main())


async def _main() -> None:
    providers = [
        Provider(
            'mlx-community/gemma-4-26B-A4B-it-bf16',
            'api_key',
            'http://127.0.0.1:8080',
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
    agent = Wednesday()
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

    tui.set_agent_name(agent.name)
    tui.set_model_name(app.provider_mgr.provider.model_name)
    if session_id is not None:
        session = await app.session_mgr.get(session_id)
        if session is not None and session.title:
            tui.set_session_title(session.title)
    tui.set_chat_handler(chat_handler)
    await tui.run_async()


if __name__ == '__main__':
    main()
