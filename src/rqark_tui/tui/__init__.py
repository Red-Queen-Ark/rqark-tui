import asyncio
import contextlib
from asyncio import AbstractEventLoop
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime

from rich.markup import escape
from rqark_app.sop.types import Sop
from rqark_app.types.session import SummaryMessage
from rqark_core.types.chat import AssistantMessage, Message, SystemMessage, ToolMessage, UserMessage
from rqark_core.types.tool import BaseTool, PlanItem
from textual.app import App, AutopilotCallbackType, ComposeResult
from textual.driver import Driver
from textual.screen import ModalScreen
from textual.worker import Worker

from rqark_tui.tui.components.dialog import YesNoDialog
from rqark_tui.tui.components.footer import ChatInput
from rqark_tui.tui.components.header import HeaderBar
from rqark_tui.tui.components.main import MessagePane
from rqark_tui.tui.components.popup import Entry, PopupSelector
from rqark_tui.tui.components.quit_handler import QuitHandler
from rqark_tui.tui.components.session import SessionTabs
from rqark_tui.tui.driver import tolerant_driver_class
from rqark_tui.tui.session import ChatSession, SessionHandler, session_uuid
from rqark_tui.tui.theme import active_theme, load_theme, resolve_name, textual_theme, theme_names, use_theme

#: Slash command the TUI answers itself: closing the session on screen.
CLOSE_COMMAND = '/close'

#: Slash command the TUI answers itself: adding a session (the ``+`` tab does the same).
NEW_COMMAND = '/new'

#: Slash command that runs long enough to need a status line while it works.
COMPACT_COMMAND = '/compact'

#: Slash command the TUI answers itself: switching palette.
THEME_COMMAND = '/theme'

#: Builds the per-session bridge to the agent app: ``(session key, app session id)``.
SessionFactory = Callable[[str, str | None], SessionHandler]

#: What a session is started with when it is restored from storage: its id, its
#: title, its last chunk and the id of the agent it was last talked to with.
Restored = tuple[str, str, Sequence[Message | SummaryMessage], str]

#: Reads what a start needs from slow storage: the restored sessions and the SOPs.
StartupLoader = Callable[[], Awaitable[tuple[list[Restored], Sequence[Sop]]]]

#: Stores the theme the user picked, so the next run starts with it.
ThemeSaver = Callable[[str], Awaitable[None]]


class AgentTUI(QuitHandler, App):
    """The rqark TUI: header bar, session tabs, message panes, popup selector and chat input.

    Every chat is a session of its own, with its own pane, worker and transcript, so
    several sessions stream at the same time. The tab strip decides which pane the
    area above the input shows; a background session keeps rendering unseen until
    its tab is selected again.
    """

    AUTO_FOCUS = 'ChatInput'

    #: Every colour the widgets draw lives in this sheet, named by ``$rq-*``
    #: tokens; the values come from the theme file (see ``theme.py``).
    CSS_PATH = 'styles/app.tcss'

    async def run(
        self, *, headless: bool = False, inline: bool = False, inline_no_clear: bool = False, mouse: bool = True, size: tuple[int, int] | None = None, auto_pilot: AutopilotCallbackType | None = None, loop: AbstractEventLoop | None = None
    ) -> None:
        await super().run_async(headless=headless, inline=inline, inline_no_clear=inline_no_clear, mouse=mouse, size=size, auto_pilot=auto_pilot)

    def __init__(self, theme: str | None = None) -> None:
        use_theme(load_theme(resolve_name(theme)))
        super().__init__()
        self.register_theme(textual_theme(active_theme()))
        self.theme = textual_theme(active_theme()).name
        self._agent_name = ''
        self._model_name = ''
        self._cloud = False
        self._tool_keys: dict[str, str] = {}
        self._sops: list[Sop] = []
        self._sessions: dict[str, ChatSession] = {}
        self._keys_by_uuid: dict[str, str] = {}
        self._active_key: str | None = None
        self._session_count = 0
        self._pending: list[Restored] = []
        self._session_factory: SessionFactory | None = None
        self._startup_loader: StartupLoader | None = None
        self._startup_running = False
        self._theme_saver: ThemeSaver | None = None
        # The tab made at mount while the loader runs, so the layout is complete
        # before storage answers. It is dropped once the stored tabs arrive, unless
        # the user has already typed into it.
        self._placeholder_key: str | None = None

    def get_driver_class(self) -> type[Driver]:
        return tolerant_driver_class(super().get_driver_class())

    def get_css_variables(self) -> dict[str, str]:
        """Textual CSS variables: the active theme's tokens as ``$rq-*``."""
        return {**super().get_css_variables(), **active_theme().variables()}

    def set_theme_saver(self, saver: ThemeSaver) -> None:
        """Set how a theme the user picked is remembered for the next run."""
        self._theme_saver = saver

    def apply_theme(self, name: str, *, persist: bool = False) -> None:
        """Switch to the theme called ``name``, repainting the whole interface.

        ``persist`` asks the configured saver to store the choice; it is left off
        for the theme read back at start, which is already stored.

        Raises:
            ThemeError: the theme does not exist.
        """
        use_theme(load_theme(name))
        self.register_theme(textual_theme(active_theme()))
        self.theme = textual_theme(active_theme()).name
        if self.is_running:
            self.screen.styles.background = active_theme().color('bg')
            self.refresh_css()
        for session in self._sessions.values():
            session.pane.repaint()
        if persist:
            self._save_theme(name)

    def _save_theme(self, name: str) -> None:
        """Store ``name`` through the saver, reporting a failure without undoing the switch."""
        saver = self._theme_saver
        if saver is None:
            return
        self.run_worker(self._run_save_theme(saver, name), name='save-theme', group='theme', exit_on_error=False)

    async def _run_save_theme(self, saver: ThemeSaver, name: str) -> None:
        try:
            await saver(name)
        except Exception as error:
            self.notify(f'Could not save the theme: {error}', severity='warning', timeout=6)

    def set_tools(self, tools: Sequence[BaseTool]) -> None:
        self._tool_keys = {tool.name: tool.display_key for tool in tools}
        for session in self._sessions.values():
            session.pane.set_tool_keys(self._tool_keys)

    def load_startup(self, loader: StartupLoader) -> None:
        """Read the stored sessions and the SOPs after the first frame.

        Cloud storage answers in seconds, and a start that waits for it shows an
        empty terminal for that whole time. With a loader set the interface is
        painted first and the tabs are added when the answer arrives; a session
        is only created up front when no loader is given.
        """
        self._startup_loader = loader

    def set_sops(self, sops: Sequence[Sop]) -> None:
        """Set the user-written SOPs the slash popup offers beside the built-in commands."""
        self._sops = list(sops)

    @property
    def sops(self) -> list[Sop]:
        """The SOPs the slash popup offers; empty until they are loaded."""
        return self._sops

    def set_session_factory(self, factory: SessionFactory) -> None:
        """Set how a new tab gets its bridge to the agent app.

        A tab opened before the factory was known (the one made at mount while the
        background start runs) gets its handler here, so it can chat from then on.
        """
        self._session_factory = factory
        for session in self._sessions.values():
            if session.handler is None:
                session.handler = factory(session.key, session.session_id)

    def open_sessions(self, sessions: Sequence[Restored]) -> None:
        """Make stored sessions tabs, in the order given; the first one is shown.

        Before the app runs the tabs are opened on mount, so the layout is composed
        once; afterwards they are appended to whatever is already on screen.
        """
        if not sessions:
            return
        if self.is_running:
            self._open_sessions(sessions)
            return
        self._pending.extend(sessions)

    def _open_sessions(self, sessions: Sequence[Restored]) -> None:
        restored = [self.new_session(session_id=session_id, title=title, messages=messages, agent_id=agent_id) for session_id, title, messages, agent_id in sessions]
        self.select_session(restored[0].key)

    def compose(self) -> ComposeResult:
        yield HeaderBar()
        yield SessionTabs()
        yield PopupSelector()
        yield ChatInput()

    def on_mount(self) -> None:
        self.screen.styles.background = active_theme().color('bg')
        header = self.query_one(HeaderBar)
        header.agent_name = self._agent_name
        header.model_name = self._model_name
        header.cloud = self._cloud
        pending, self._pending = self._pending, []
        if pending:
            self._open_sessions(pending)
        else:
            session = self.new_session()
            if self._startup_loader is not None:
                self._placeholder_key = session.key
                self._startup_running = True
                self.run_worker(self._run_startup(), name='startup', group='startup', exit_on_error=False)
        active = self.active_session
        if active is not None and active.agent_name:
            header.agent_name = active.agent_name
        self.query_one(ChatInput).focus()

    async def _run_startup(self) -> None:
        loader = self._startup_loader
        if loader is None:
            return
        sessions: list[Restored] = []
        sops: Sequence[Sop] = []
        try:
            sessions, sops = await loader()
        except Exception as error:
            self.notify(str(error), severity='error', timeout=8)
        finally:
            self._startup_running = False
        self.set_sops(sops)
        if sessions:
            await self._drop_placeholder()
            self.open_sessions(sessions)
            active = self.active_session
            if active is not None and active.agent_name:
                self.query_one(HeaderBar).agent_name = active.agent_name

    async def _drop_placeholder(self) -> None:
        """Remove the tab made at mount, so the restored tabs are the only ones.

        A placeholder the user has typed into, or that already holds a message, is
        kept: throwing away something typed while waiting would be worse than one
        extra tab.
        """
        key = self._placeholder_key
        self._placeholder_key = None
        session = self._sessions.get(key) if key is not None else None
        if session is None:
            return
        if session.session_id is not None or session.busy or session.draft or not session.pane.is_empty or self.query_one(ChatInput).text:
            return
        await self._drop_session(session)

    def set_agent_name(self, name: str) -> None:
        self._agent_name = name
        if self.is_running:
            self.query_one(HeaderBar).agent_name = name

    def set_model_name(self, name: str) -> None:
        self._model_name = name
        if self.is_running:
            self.query_one(HeaderBar).model_name = name

    def set_cloud_mode(self, cloud: bool) -> None:
        self._cloud = cloud
        if self.is_running:
            self.query_one(HeaderBar).cloud = cloud

    # --- sessions -----------------------------------------------------------

    @property
    def active_session(self) -> ChatSession | None:
        """The session whose transcript the pane is showing."""
        return self._sessions.get(self._active_key) if self._active_key is not None else None

    @property
    def sessions(self) -> list[ChatSession]:
        """Every open session, in the order their tabs were added."""
        return list(self._sessions.values())

    @property
    def active_key(self) -> str | None:
        return self._active_key

    @property
    def pane(self) -> MessagePane | None:
        """The active session's pane."""
        session = self.active_session
        return session.pane if session is not None else None

    def session_pane(self, key: str | None) -> MessagePane | None:
        session = self._sessions.get(key) if key is not None else None
        return session.pane if session is not None else None

    def session_key(self, agent_id: str = '', path: tuple[str, ...] = ()) -> str | None:
        """The tab an event belongs to, from the session uuid carried by its agent id."""
        uuid = session_uuid(agent_id, path)
        return self._keys_by_uuid.get(uuid) if uuid else None

    def session_agent(self, key: str) -> tuple[str, str]:
        """The agent id and name a tab was last talked to with, empty before its first turn."""
        session = self._sessions.get(key)
        if session is None:
            return ('', '')
        return (session.agent_id, session.agent_name)

    def set_session_agent(self, key: str, agent_id: str, name: str) -> None:
        """Record the agent a tab talks to, and show it while the tab is on screen."""
        session = self._sessions.get(key)
        if session is None:
            return
        session.agent_id = agent_id
        session.agent_name = name
        if key == self._active_key:
            self.set_agent_name(name)

    def bind_session(self, key: str, session_id: str) -> None:
        """Point an app session at a tab, so its events reach that tab's pane."""
        self._keys_by_uuid[session_id] = key
        session = self._sessions.get(key)
        if session is not None:
            session.session_id = session_id

    def new_session(self, *, session_id: str | None = None, title: str = '', messages: Sequence[Message | SummaryMessage] | None = None, agent_id: str = '') -> ChatSession:
        """Add a tab with its own pane and switch to it."""
        self._session_count += 1
        key = f'session-{self._session_count}'
        pane = MessagePane(id=f'pane-{key}')
        pane.display = False
        pane.set_tool_keys(self._tool_keys)
        session = ChatSession(key=key, ordinal=self._session_count, pane=pane, session_id=session_id, title=title, agent_id=agent_id)
        self._sessions[key] = session
        if self._session_factory is not None:
            session.handler = self._session_factory(key, session_id)
        if session_id is not None:
            self._keys_by_uuid[session_id] = key
        self.mount(pane, before=self.query_one(PopupSelector))
        self.query_one(SessionTabs).add_session(key, session.label)
        if messages:
            self._replay(session, messages)
        self.select_session(key)
        return session

    def select_session(self, key: str) -> None:
        """Show ``key``'s transcript, hand it the input and keep the old draft.

        The input always takes focus back: clicking a tab (or its close mark, even
        when the close is refused) moves focus to the tab strip, and without this
        the next keystrokes would go nowhere.
        """
        if key not in self._sessions:
            return
        chat = self.query_one(ChatInput)
        if key != self._active_key:
            current = self.active_session
            if current is not None:
                current.draft = chat.text
                current.pane.display = False
            session = self._sessions[key]
            self._active_key = key
            session.pane.display = True
            self.query_one(SessionTabs).activate(key)
            self._show_plan(session)
            if session.agent_name:
                self.set_agent_name(session.agent_name)
            chat.text = session.draft
        chat.focus()

    def close_session(self, key: str) -> None:
        """Ask to remove a session, then cancel its chat, drop its tab and delete its transcript.

        The last tab is kept — there is always a session on screen, so emptying a
        conversation means ``/clear`` rather than closing it. Asking goes through a
        confirmation dialog because the stored transcript is gone for good.
        """
        session = self._sessions.get(key)
        if session is None:
            return
        if len(self._sessions) <= 1:
            self.notify('Cannot close the last session — use /clear instead', severity='warning', timeout=4)
            self._focus_input()
            return
        if self.query_one(ChatInput).popup_active:
            self._focus_input()
            return
        if self._dialog_open:
            return
        self._focus_input()
        self.push_screen(YesNoDialog(f'Close {session.label} and delete its conversation?', title='Close session?', yes_label='Close', no_label='Cancel', default_yes=False), lambda confirmed: self._close_confirmed(key, confirmed))

    @property
    def _dialog_open(self) -> bool:
        """True while a modal dialog owns the keys: the quit confirmation, or another close."""
        return isinstance(self.screen, ModalScreen)

    def _close_confirmed(self, key: str, confirmed: bool | None) -> None:
        """Dialog dismissal: only a yes removes the session."""
        self._focus_input()
        session = self._sessions.get(key)
        if not confirmed or session is None:
            return
        self.run_worker(self._close_session(session), name=f'close-{key}', group='agent', exit_on_error=False)

    def _focus_input(self) -> None:
        self.query_one(ChatInput).focus()

    async def _close_session(self, session: ChatSession) -> None:
        worker = session.worker
        await self._drop_session(session)
        if worker is not None and worker.is_running:
            worker.cancel()
            # Wait for the cancelled chat to unwind before dropping the stored
            # transcript, so its own save cannot resurrect the deleted session.
            with contextlib.suppress(Exception):
                await worker.wait()
        handler = session.handler
        if handler is not None:
            await handler.close()

    def close_active_session(self) -> None:
        """Remove the session on screen (nothing happens when it is the only one)."""
        session = self.active_session
        if session is not None:
            self.close_session(session.key)

    def on_message_pane_revert_requested(self, event: MessagePane.RevertRequested) -> None:
        """``[revert]`` clicked: confirm, then drop that user message and everything after it."""
        session = self._session_for_pane(event.control)
        if session is None or session.handler is None:
            return
        if session.busy:
            self.notify('Still processing — please wait', severity='warning', timeout=4)
            return
        if self._dialog_open:
            return
        self._focus_input()
        message_id = event.message_id
        self.push_screen(
            YesNoDialog('Revert to this message? It and everything after it will be removed.', title='Revert?', yes_label='Revert', no_label='Cancel', default_yes=False),
            lambda confirmed: self._revert_confirmed(session, message_id, confirmed),
        )

    def _session_for_pane(self, pane: MessagePane) -> ChatSession | None:
        for session in self._sessions.values():
            if session.pane is pane:
                return session
        return None

    def _revert_confirmed(self, session: ChatSession, message_id: str, confirmed: bool | None) -> None:
        """Dialog dismissal: only a yes drops the message and everything after it."""
        self._focus_input()
        if not confirmed:
            return
        self.run_worker(self._revert_session(session, message_id), name=f'revert-{session.key}', group='agent', exit_on_error=False)

    async def _revert_session(self, session: ChatSession, message_id: str) -> None:
        handler = session.handler
        if handler is None:
            return
        try:
            reverted = await handler.revert(message_id)
        except Exception as error:
            self.notify(str(error), severity='error', timeout=8)
            return
        if reverted is None:
            self.notify('Nothing to revert', severity='warning', timeout=4)
            return
        self.replay_session(session.key, reverted.get_last_chunk())
        self.notify('Reverted')

    async def _drop_session(self, session: ChatSession) -> None:
        """Take a session off screen: its tab, its pane, its routings and its draft.

        The tab strip is updated before the successor is selected: removing the active
        tab makes ``Tabs`` fall back to the ``+`` tab on its own, and only re-selecting
        afterwards wins that race.
        """
        key = session.key
        successor = self._successor_key(key) if key == self._active_key else None
        self._sessions.pop(key, None)
        if session.session_id is not None:
            self._keys_by_uuid.pop(session.session_id, None)
        session.pane.remove()
        if key == self._active_key:
            self._active_key = None
        await self.query_one(SessionTabs).remove_session(key)
        if successor is not None:
            self.select_session(successor)

    def _successor_key(self, key: str) -> str | None:
        """The tab to show once ``key`` goes: the one after it, else the last one left."""
        keys = [other for other in self._sessions if other != key]
        if not keys:
            return None
        index = list(self._sessions).index(key)
        return keys[min(index, len(keys) - 1)]

    def on_session_tabs_close_requested(self, event: SessionTabs.CloseRequested) -> None:
        self.close_session(event.key)

    def set_session_title(self, key: str, title: str) -> None:
        """Name a session: its tab label."""
        session = self._sessions.get(key)
        if session is None or session.title == title:
            return
        session.title = title
        self.query_one(SessionTabs).set_label(key, session.label)

    def replay_session(self, key: str, messages: Sequence[Message | SummaryMessage]) -> None:
        """Rebuild a session's pane from ``messages`` (its history was rewritten)."""
        session = self._sessions.get(key)
        if session is None:
            return
        session.pane.clear()
        self._replay(session, messages)

    def show_status(self, key: str, text: str) -> None:
        """Show a session's transient status line (progress of a running command)."""
        pane = self.session_pane(key)
        if pane is not None:
            pane.show_status(text)

    def hide_status(self, key: str) -> None:
        """Drop a session's transient status line."""
        pane = self.session_pane(key)
        if pane is not None:
            pane.hide_status()

    def clear_session(self, key: str) -> None:
        """Empty a session: its transcript, its title, its plan and its stored id."""
        session = self._sessions.get(key)
        if session is None:
            return
        session.pane.clear()
        if session.session_id is not None:
            self._keys_by_uuid.pop(session.session_id, None)
        session.session_id = None
        session.title = ''
        session.plan = []
        self.query_one(SessionTabs).set_label(key, session.label)
        if key == self._active_key:
            self._show_plan(session)

    def on_session_tabs_selected(self, event: SessionTabs.Selected) -> None:
        self.select_session(event.key)

    def on_session_tabs_new_requested(self, event: SessionTabs.NewRequested) -> None:
        self.new_session()

    # --- transcript appends -------------------------------------------------

    def _pane_for(self, key: str | None, agent_id: str = '', path: tuple[str, ...] = ()) -> MessagePane | None:
        """The pane an append targets: an explicit key, an event's session, else the active one."""
        if key is not None:
            return self.session_pane(key)
        if agent_id or path:
            resolved = self.session_key(agent_id, path)
            return self.session_pane(resolved)
        return self.pane

    def _replay(self, session: ChatSession, messages: Sequence[Message | SummaryMessage]) -> None:
        pane = session.pane
        agent_id = self._agent_name
        for m in messages:
            at = getattr(m, 'created_at', None)
            if isinstance(m, (SummaryMessage, SystemMessage)):
                pane.append_system(m.content, at)
            elif isinstance(m, UserMessage):
                pane.append_message(m.content, at, m.images, m.id)
            elif isinstance(m, AssistantMessage):
                if m.reasoning_content:
                    pane.append_think_delta(m.reasoning_content, at, agent_id)
                if m.content:
                    pane.append_agent_delta(m.content, at, agent_id)
                if m.tool_calls:
                    for call in m.tool_calls:
                        pane.append_tool_call(call.name, call.arguments, at, agent_id)
                else:
                    pane.close_agent_message(agent_id)
            elif isinstance(m, ToolMessage):
                pane.append_tool_result(m.tool_name or '', m.content, at, agent_id)

    def append_message(self, text: str, at: datetime | None = None, images: Sequence[str] | None = None, message_id: str = '', key: str | None = None) -> None:
        pane = self._pane_for(key)
        if pane is not None:
            pane.append_message(text, at, images, message_id)

    def set_user_message_id(self, message_id: str, agent_id: str = '', path: tuple[str, ...] = ()) -> None:
        """Attach a live user message's app id to its pane block, making it revertible."""
        pane = self._pane_for(None, agent_id, path)
        if pane is not None:
            pane.set_last_user_message_id(message_id)

    def append_agent_delta(self, text: str, at: datetime | None = None, agent_id: str = '', path: tuple[str, ...] = (), key: str | None = None) -> None:
        pane = self._pane_for(key, agent_id, path)
        if pane is not None:
            pane.append_agent_delta(text, at, agent_id, path)

    def append_think_delta(self, text: str, at: datetime | None = None, agent_id: str = '', path: tuple[str, ...] = (), key: str | None = None) -> None:
        pane = self._pane_for(key, agent_id, path)
        if pane is not None:
            pane.append_think_delta(text, at, agent_id, path)

    def close_agent_message(self, agent_id: str = '', path: tuple[str, ...] = (), key: str | None = None) -> None:
        pane = self._pane_for(key, agent_id, path)
        if pane is not None:
            pane.close_agent_message(agent_id, path)

    def append_tool_call(self, name: str, arguments: str = '', at: datetime | None = None, agent_id: str = '', path: tuple[str, ...] = (), key: str | None = None) -> None:
        pane = self._pane_for(key, agent_id, path)
        if pane is not None:
            pane.append_tool_call(name, arguments, at, agent_id, path)

    def append_tool_result(self, name: str, content: str, at: datetime | None = None, agent_id: str = '', path: tuple[str, ...] = (), key: str | None = None) -> None:
        pane = self._pane_for(key, agent_id, path)
        if pane is not None:
            pane.append_tool_result(name, content, at, agent_id, path)

    def append_error(self, text: str, at: datetime | None = None, agent_id: str = '', path: tuple[str, ...] = (), key: str | None = None) -> None:
        pane = self._pane_for(key, agent_id, path)
        if pane is not None:
            pane.append_error(text, at)

    def append_system(self, text: str, at: datetime | None = None, key: str | None = None) -> None:
        pane = self._pane_for(key)
        if pane is not None:
            pane.append_system(text, at)

    def clear_messages(self) -> None:
        """Empty the session on screen."""
        session = self.active_session
        if session is not None:
            self.clear_session(session.key)

    # --- plans --------------------------------------------------------------

    @staticmethod
    def _plan_text(items: Sequence[PlanItem]) -> str:
        return '\n'.join(f'[{item.icon}] {item.content}' for item in items)

    def show_plan(self, items: Sequence[PlanItem], agent_id: str = '', path: tuple[str, ...] = ()) -> None:
        """Record a plan and, for the session on screen, show it in the popup."""
        key = self.session_key(agent_id, path) if (agent_id or path) else self._active_key
        session = self._sessions.get(key) if key is not None else None
        if session is None:
            return
        session.plan = list(items)
        if key == self._active_key:
            self._show_plan(session)

    def _show_plan(self, session: ChatSession) -> None:
        """Show the session's plan, leaving an open picker on screen."""
        if self.query_one(ChatInput).popup_active:
            return
        popup = self.query_one(PopupSelector)
        if session.plan:
            popup.show_text(self._plan_text(session.plan), title='Plan')
            return
        popup.hide()

    # --- chat ---------------------------------------------------------------

    def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        session = self.active_session
        if session is None:
            self.query_one(ChatInput).text = event.text
            self.notify('Still starting — please wait', severity='warning', timeout=4)
            return
        text = event.text
        images = event.images
        command = text.split(maxsplit=1)[0]
        if command == NEW_COMMAND:
            self.new_session()
            return
        if command == CLOSE_COMMAND:
            self.close_active_session()
            return
        if command == THEME_COMMAND:
            self._switch_theme(text.partition(' ')[2].strip())
            return
        if command == COMPACT_COMMAND and session.busy:
            self.notify('Still processing — please wait', severity='warning', timeout=4)
            return
        if text.startswith('/') and session.handler is not None:
            self.run_worker(self._run_command(session, text), name=f'command-{session.key}', group='agent', exit_on_error=False)
            return
        if session.busy:
            self.notify('Still processing — please wait', severity='warning', timeout=4)
            return
        if session.handler is None and self._startup_running:
            # The background start has not built the bridge to the agent app yet.
            # The input clears itself on submit, so the text is put back.
            self.query_one(ChatInput).text = text
            self.notify('Still starting — please wait', severity='warning', timeout=4)
            return
        session.pane.append_message(text, images=images)
        if session.handler is None:
            return
        session.busy = True
        self.query_one(SessionTabs).set_busy(session.key, True)
        session.worker = self.run_worker(self._run_chat(session, text, images), name=f'chat-{session.key}', group='agent', exit_on_error=False)

    def _switch_theme(self, name: str) -> None:
        names = theme_names()
        if not name:
            self.run_worker(self._pick_theme(), name='theme-picker', group='agent', exit_on_error=False)
            return
        if name not in names:
            self.notify(f'Unknown theme {name}; choose {", ".join(names)}', severity='warning', timeout=4)
            return
        self.apply_theme(name, persist=True)
        self.notify(f'Theme: {name}', timeout=3)

    async def _pick_theme(self) -> None:
        """Offer the themes in the popup selector, the way ``/models`` and ``/agents`` do."""
        names = theme_names()
        current = active_theme().name
        entries = [(f'[b]{escape(load_theme(name).label)}[/b] {name}', name) for name in names]
        index = names.index(current) if current in names else 0
        entry = await self.pick(entries, title='Theme', index=index)
        if entry is not None:
            self.apply_theme(entry[1], persist=True)

    async def _run_chat(self, session: ChatSession, text: str, images: list[str]) -> None:
        handler = session.handler
        if handler is None:
            return
        try:
            await handler.chat(text, images)
        except Exception as error:
            self.notify(str(error), severity='error', timeout=8)
        finally:
            session.busy = False
            self.query_one(SessionTabs).set_busy(session.key, False)

    async def _run_command(self, session: ChatSession, command: str) -> None:
        handler = session.handler
        if handler is None:
            return
        # A command holds the session while it runs: `/compact` spends seconds on the
        # provider, and its own guard (`on_chat_input_submitted`) keeps a second
        # submission from racing the transcript rewrite.
        session.busy = True
        self.query_one(SessionTabs).set_busy(session.key, True)
        try:
            reply = await handler.command(command)
        except Exception as error:
            self.notify(str(error), severity='error', timeout=8)
            return
        finally:
            session.busy = False
            self.query_one(SessionTabs).set_busy(session.key, False)
        if reply:
            session.pane.append_system(reply)

    def cancel_chat(self, key: str | None = None) -> None:
        """Cancel the worker of ``key`` (the session on screen by default)."""
        session = self._sessions.get(key) if key is not None else self.active_session
        if session is None:
            return
        worker: Worker[None] | None = session.worker
        if worker is not None and worker.is_running:
            worker.cancel()

    async def pick(self, entries: Sequence[Entry], *, title: str = '', index: int = 0) -> Entry | None:
        """Show entries in the popup selector and resolve with the chosen entry (None when dismissed)."""
        if not entries:
            return None
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Entry | None] = loop.create_future()

        def done(entry: Entry | None) -> None:
            if not future.done():
                future.set_result(entry)

        self.query_one(ChatInput).begin_pick(list(entries), title=title, index=index, on_done=done)
        return await future
