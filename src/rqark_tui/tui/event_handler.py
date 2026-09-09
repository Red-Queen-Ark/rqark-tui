import asyncio

from rich.markup import escape
from rqark_app.agent.manager import AgentManager
from rqark_app.app import AgentApp
from rqark_core.types.chat import AssistantMessage, Chunk, UserMessage
from rqark_core.types.event import AgentPayload

from rqark_tui.config.manager import ConfigManager
from rqark_tui.tui import AgentTUI


class EventHandler:
    """Bridges AgentApp events with TUI actions: chat submit and slash command dispatch."""

    def __init__(
        self,
        app: AgentApp,
        tui: AgentTUI,
        agent_mgr: AgentManager,
        config_mgr: ConfigManager,
        session_id: str | None,
    ) -> None:
        self.app = app
        self.tui = tui
        self.agent_mgr = agent_mgr
        self.config_mgr = config_mgr
        self.session_id = session_id
        self._title_tasks: set[asyncio.Task] = set()
        self._stream_active = False
        self._stop_requested = False
        self._last_chat_text = ''
        self._stream_content = ''
        self._stream_reasoning = ''
        self._register_stream_tracking()

    def _register_stream_tracking(self) -> None:
        @self.app.on_think()
        async def track_think(ev: AgentPayload[Chunk]) -> None:
            if self._stream_active:
                self._stream_reasoning += str(ev.payload.content)

        @self.app.on_content()
        async def track_content(ev: AgentPayload[Chunk]) -> None:
            if self._stream_active:
                self._stream_content += str(ev.payload.content)

    async def gen_title(self, session_uuid: str, first_message: str) -> None:
        titled = await self.app.chat_helper.gen_title(session_uuid, first_message)
        if titled is not None and titled.title:
            self.tui.set_session_title(titled.title)

    async def chat(self, text: str) -> None:
        self._last_chat_text = text
        self._stream_content = ''
        self._stream_reasoning = ''
        self._stream_active = True
        self._stop_requested = False
        try:
            if self.session_id is None:
                session = await self.app.session_mgr.create()
                self.session_id = session.uuid
            session = await self.app.chat(text, self.agent_mgr.agent, session_id=self.session_id)
            self.session_id = session.uuid
            self.config_mgr.dir_cache.set_session_id(self.config_mgr.cwd_hash, self.session_id)
            if not session.title:
                task = asyncio.create_task(self.gen_title(session.uuid, text))
                self._title_tasks.add(task)
                task.add_done_callback(self._title_tasks.discard)
        except asyncio.CancelledError:
            if self._stop_requested:
                await self._save_partial()
                return
            raise
        finally:
            self._stream_active = False

    async def _save_partial(self) -> None:
        content = self._stream_content
        reasoning = self._stream_reasoning
        if not content and not reasoning:
            return
        if self.session_id is None:
            return
        session = await self.app.session_mgr.get(self.session_id)
        if session is None:
            return
        partial = AssistantMessage(content=content, reasoning_content=reasoning or None)
        messages = [*session.get_last_chunk_for_chat(), UserMessage(self._last_chat_text), partial]
        session.update_history_to_last_chunk(messages)
        await self.app.session_mgr.save(session.uuid)
        self.config_mgr.dir_cache.set_session_id(self.config_mgr.cwd_hash, self.session_id)

    async def command(self, command: str) -> str | None:
        name, _, arg = command.partition(' ')
        arg = arg.strip()
        match name:
            case '/clear':
                self.tui.cancel_chat()
                if self.session_id is not None:
                    await self.app.session_mgr.delete(self.session_id)
                    self.session_id = None
                self.tui.clear_messages()
                self.tui.set_session_title('')
                return 'Conversation cleared'
            case '/stop':
                self._stop_requested = True
                self.tui.cancel_chat()
                return 'Stopped'
            case '/models':
                providers = self.app.provider_mgr.providers
                if not providers:
                    return 'No models available'
                entries = [(f'[b]{escape(p.name)}[/b] {escape(p.api_base)}', str(i)) for i, p in enumerate(providers)]
                entry = await self.tui.pick(entries, title='Models', index=self.app.provider_mgr.cur_index)
                if entry is None:
                    return None
                return self._switch_model(int(entry[1]))
            case '/agents':
                agents = self.agent_mgr.agents
                if not agents:
                    return 'No agents available'
                entries = [(f'[b]{escape(agent.name)}[/b]', str(i)) for i, agent in enumerate(agents)]
                entry = await self.tui.pick(entries, title='Agents', index=self.agent_mgr.cur_index)
                if entry is None:
                    return None
                return self._switch_agent(int(entry[1]))
            case _:
                return f'Unknown command: {name}'

    def _switch_model(self, index: int) -> str:
        manager = self.app.provider_mgr
        old = manager.provider.name
        manager.switch_to(index)
        new = manager.provider.name
        self.tui.set_model_name(new)
        return f'Model: {old} -> {new}'

    def _switch_agent(self, index: int) -> str:
        manager = self.agent_mgr
        old = manager.agent.name
        manager.switch_to(index)
        new = manager.agent.name
        self.tui.set_agent_name(new)
        return f'Agent: {old} -> {new}'
