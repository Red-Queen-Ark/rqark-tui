import asyncio

from rich.markup import escape
from rqark_app.agent.manager import AgentManager
from rqark_app.app import AgentApp
from rqark_app.compact import compact_messages
from rqark_app.config.manager import ConfigManager
from rqark_app.tools.context import AGENT_KEY, CLIENT_KEY, SOURCE_KEY
from rqark_app.types.session import Session
from rqark_core.types.chat import AssistantMessage, Chunk, UserMessage
from rqark_core.types.event import AgentPayload

from rqark_tui.tui import AgentTUI


class EventHandler:
    """Bridges AgentApp events with TUI actions for one session tab.

    Every tab owns its own handler, so two sessions can stream at the same time
    without sharing buffers; the stream listeners below only collect the events of
    the session this handler was built for.
    """

    def __init__(self, app: AgentApp, tui: AgentTUI, agent_mgr: AgentManager, config_mgr: ConfigManager, session_id: str | None, key: str = '') -> None:
        self.app = app
        self.tui = tui
        self.agent_mgr = agent_mgr
        self.config_mgr = config_mgr
        self.session_id = session_id
        self.key = key
        self._title_tasks: set[asyncio.Task] = set()
        self._stream_active = False
        self._stop_requested = False
        self._last_chat_text = ''
        self._last_chat_images: list[str] = []
        self._stream_content = ''
        self._stream_reasoning = ''
        self._register_stream_tracking()

    def _register_stream_tracking(self) -> None:
        @self.app.on_think()
        async def track_think(ev: AgentPayload[Chunk]) -> None:
            if self._owns(ev) and self._stream_active:
                self._stream_reasoning += str(ev.payload.content)

        @self.app.on_content()
        async def track_content(ev: AgentPayload[Chunk]) -> None:
            if self._owns(ev) and self._stream_active:
                self._stream_content += str(ev.payload.content)

    def _owns(self, ev: AgentPayload[Chunk]) -> bool:
        """True when an event is the main agent of this handler's session (never a subagent)."""
        if ev.path:
            return False
        return self.key == '' or self.tui.session_key(ev.agent_id, ev.path) == self.key

    def _extras(self) -> dict[str, object] | None:
        """The cloud connection the tools and prompts of this turn read."""
        client = self.config_mgr.cloud_client
        agent_id = self.agent_mgr.agent.id
        if client is None or not agent_id:
            return None
        return {CLIENT_KEY: client, AGENT_KEY: agent_id, SOURCE_KEY: self.config_mgr.source}

    async def gen_title(self, session_uuid: str, first_message: str) -> None:
        titled = await self.app.chat_helper.gen_title(session_uuid, first_message)
        if titled is not None and titled.title:
            self.tui.set_session_title(self.key, titled.title)

    async def chat(self, text: str, images: list[str] | None = None) -> None:
        self._last_chat_text = text
        self._last_chat_images = list(images) if images else []
        self._stream_content = ''
        self._stream_reasoning = ''
        self._stream_active = True
        self._stop_requested = False
        try:
            if self.session_id is None:
                session = await self.app.session_mgr.create()
                self.session_id = session.uuid
                self.tui.bind_session(self.key, session.uuid)
            session = await self.app.chat(text, self.agent_mgr.agent, session_id=self.session_id, images=images, extras=self._extras())
            self.session_id = session.uuid
            self.config_mgr.dir_cache.set_session_id(self.config_mgr.cwd_hash, self.session_id)
            if not session.title and text:
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
        messages = [*session.get_last_chunk_for_chat(), UserMessage(self._last_chat_text, images=list(self._last_chat_images)), partial]
        session.update_history_to_last_chunk(messages)
        await self.app.session_mgr.save(session.uuid)
        self.config_mgr.dir_cache.set_session_id(self.config_mgr.cwd_hash, self.session_id)

    def forget_session(self) -> None:
        """Stop resuming this session in the directory: its stored transcript is gone."""
        session_id, self.session_id = self.session_id, None
        if session_id is not None:
            self.config_mgr.dir_cache.remove_session_id(self.config_mgr.cwd_hash, session_id)

    async def close(self) -> None:
        """Delete this session's stored transcript; the tab it belonged to is gone."""
        if self.session_id is None:
            return
        await self.app.session_mgr.delete(self.session_id)
        self.forget_session()

    async def revert(self, message_id: str) -> Session | None:
        """Trim the session back to the user message ``message_id`` (None when impossible)."""
        if self.session_id is None:
            return None
        return await self.app.session_mgr.revert(self.session_id, message_id)

    async def command(self, command: str) -> str | None:
        name, _, arg = command.partition(' ')
        arg = arg.strip()
        match name:
            case '/clear':
                self.tui.cancel_chat(self.key)
                if self.session_id is not None:
                    await self.app.session_mgr.delete(self.session_id)
                    self.forget_session()
                self._stream_content = ''
                self._stream_reasoning = ''
                self.tui.clear_session(self.key)
                return 'Conversation cleared'
            case '/stop':
                self._stop_requested = True
                self.tui.cancel_chat(self.key)
                return 'Stopped'
            case '/compact':
                if self.session_id is None:
                    return 'Nothing to compact'
                session = await self.app.session_mgr.get(self.session_id)
                if session is None:
                    return 'Nothing to compact'
                messages = session.get_last_chunk_for_chat()
                if not compact_messages(messages):
                    return 'Nothing to compact'
                self.tui.show_status(self.key, 'Compacting…')
                try:
                    summary = await self.app.compactor.get_summary(messages)
                finally:
                    self.tui.hide_status(self.key)
                if summary is None:
                    return 'Compaction failed, the conversation is unchanged'
                session.history.append(summary)
                await self.app.session_mgr.save(session.uuid)
                self.tui.replay_session(self.key, session.get_last_chunk())
                return 'Conversation compacted'
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
