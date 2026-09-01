from collections.abc import Awaitable, Callable

from rqark_core.types.tool import PlanItem
from textual.app import App, ComposeResult
from textual.worker import Worker

from rqark_tui.tui.completion import CompletionPopup, expand_file_refs
from rqark_tui.tui.footer import ChatInput
from rqark_tui.tui.header import HeaderBar
from rqark_tui.tui.main import MessagePane
from rqark_tui.tui.plan import PlanPanel
from rqark_tui.tui.quit_handler import QuitHandler


class AgentTUI(QuitHandler, App):
    """The rqark TUI: header bar, message pane, plan panel, completion popup and chat input."""

    def __init__(self):
        super().__init__()
        self._agent_name = ''
        self._model_name = ''
        self._session_title = ''
        self._plan_items: list[PlanItem] = []
        self._chat_handler: Callable[[str], Awaitable[None]] | None = None
        self._command_handler: Callable[[str], Awaitable[str | None]] | None = None
        self._chat_worker: Worker | None = None
        self._chat_busy = False

    def compose(self) -> ComposeResult:
        yield HeaderBar()
        yield MessagePane()
        yield PlanPanel()
        yield CompletionPopup()
        yield ChatInput()

    def on_mount(self) -> None:
        self.screen.styles.background = '#141414'
        header = self.query_one(HeaderBar)
        header.agent_name = self._agent_name
        header.model_name = self._model_name
        header.session_title = self._session_title
        self.query_one(PlanPanel).set_plan(self._plan_items)

    def set_agent_name(self, name: str) -> None:
        self._agent_name = name
        if self.is_running:
            self.query_one(HeaderBar).agent_name = name

    def set_model_name(self, name: str) -> None:
        self._model_name = name
        if self.is_running:
            self.query_one(HeaderBar).model_name = name

    def set_session_title(self, title: str) -> None:
        self._session_title = title
        if self.is_running:
            self.query_one(HeaderBar).session_title = title

    def set_plan(self, items: list[PlanItem]) -> None:
        self._plan_items = list(items)
        if self.is_running:
            self.query_one(PlanPanel).set_plan(items)

    def set_chat_handler(self, handler: Callable[[str], Awaitable[None]]) -> None:
        self._chat_handler = handler

    def set_command_handler(self, handler: Callable[[str], Awaitable[str | None]]) -> None:
        self._command_handler = handler

    def append_agent_delta(self, text: str) -> None:
        self.query_one(MessagePane).append_agent_delta(self._agent_name, text)

    def append_think_delta(self, text: str) -> None:
        self.query_one(MessagePane).append_think_delta(text)

    def close_agent_message(self) -> None:
        self.query_one(MessagePane).close_agent_message()

    def append_tool_call(self, name: str, arguments: str) -> None:
        self.query_one(MessagePane).append_tool_call(name, arguments)

    def append_tool_result(self, name: str, content: str) -> None:
        self.query_one(MessagePane).append_tool_result(name, content)

    def append_error(self, text: str) -> None:
        self.query_one(MessagePane).append_error(text)

    def append_system(self, text: str) -> None:
        self.query_one(MessagePane).append_system(text)

    def clear_messages(self) -> None:
        self.query_one(MessagePane).clear()
        self.query_one(PlanPanel).set_plan([])

    def cancel_chat(self) -> None:
        worker = self._chat_worker
        if worker is not None and worker.is_running:
            worker.cancel()

    def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        text = event.text
        if text.startswith('/'):
            self.run_worker(self._run_command(text), name='command', group='agent', exit_on_error=False)
            return
        if self._chat_busy:
            self.notify('Still processing — type /stop to cancel', severity='warning', timeout=4)
            return
        self.query_one(MessagePane).append_message(text)
        if self._chat_handler is None:
            return
        self._chat_busy = True
        self._chat_worker = self.run_worker(
            self._run_chat(expand_file_refs(text)),
            name='agent-chat',
            group='agent',
            exit_on_error=False,
        )

    async def _run_command(self, text: str) -> None:
        handler = self._command_handler
        if handler is None:
            self.append_system('Command handler not available')
            return
        try:
            result = await handler(text)
        except Exception as error:
            self.notify(str(error), severity='error', timeout=8)
            return
        if result:
            self.append_system(result)

    async def _run_chat(self, text: str) -> None:
        handler = self._chat_handler
        if handler is None:
            return
        try:
            await handler(text)
        except Exception as error:
            self.notify(str(error), severity='error', timeout=8)
        finally:
            self._chat_busy = False
