from collections.abc import Awaitable, Callable

from textual.app import App, ComposeResult

from rqark_tui.tui.footer import ChatInput
from rqark_tui.tui.header import HeaderBar
from rqark_tui.tui.main import MessagePane
from rqark_tui.tui.quit_handler import QuitHandler


class AgentTUI(QuitHandler, App):
    """The rqark TUI: header bar, scrollable message pane and chat input."""

    def __init__(self):
        super().__init__()
        self._agent_name = ''
        self._model_name = ''
        self._session_title = ''
        self._chat_handler: Callable[[str], Awaitable[None]] | None = None

    def compose(self) -> ComposeResult:
        yield HeaderBar()
        yield MessagePane()
        yield ChatInput()

    def on_mount(self) -> None:
        self.screen.styles.background = '#141414'
        header = self.query_one(HeaderBar)
        header.agent_name = self._agent_name
        header.model_name = self._model_name
        header.session_title = self._session_title

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

    def set_chat_handler(self, handler: Callable[[str], Awaitable[None]]) -> None:
        self._chat_handler = handler

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

    def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        self.query_one(MessagePane).append_message(event.text)
        if self._chat_handler is None:
            return
        event.control.disabled = True
        self.run_worker(self._run_chat(event.text), name='agent-chat', group='agent', exit_on_error=False)

    async def _run_chat(self, text: str) -> None:
        handler = self._chat_handler
        if handler is None:
            return
        try:
            await handler(text)
        except Exception as error:
            self.notify(str(error), severity='error', timeout=8)
        finally:
            self.query_one(ChatInput).disabled = False
