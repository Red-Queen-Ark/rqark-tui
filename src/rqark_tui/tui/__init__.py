from asyncio import AbstractEventLoop
from collections.abc import Awaitable, Callable

from textual.app import App, AutopilotCallbackType, ComposeResult
from textual.worker import Worker

from rqark_tui.tui.components.completion import CompletionPopup, expand_file_refs
from rqark_tui.tui.components.footer import ChatInput
from rqark_tui.tui.components.header import HeaderBar
from rqark_tui.tui.components.main import MessagePane
from rqark_tui.tui.components.quit_handler import QuitHandler


class AgentTUI(QuitHandler, App):
    """The rqark TUI: header bar, message pane, completion popup and chat input."""

    async def run(
        self,
        *,
        headless: bool = False,
        inline: bool = False,
        inline_no_clear: bool = False,
        mouse: bool = True,
        size: tuple[int, int] | None = None,
        auto_pilot: AutopilotCallbackType | None = None,
        loop: AbstractEventLoop | None = None,
    ) -> None:
        await super().run_async(
            headless=headless,
            inline=inline,
            inline_no_clear=inline_no_clear,
            mouse=mouse,
            size=size,
            auto_pilot=auto_pilot,
        )

    def __init__(self):
        super().__init__()
        self._agent_name = ''
        self._model_name = ''
        self._session_title = ''
        self._chat_handler: Callable[[str], Awaitable[None]] | None = None
        self._chat_worker: Worker | None = None
        self._chat_busy = False

    def compose(self) -> ComposeResult:
        yield HeaderBar()
        yield MessagePane()
        yield CompletionPopup()
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

    def append_system(self, text: str) -> None:
        self.query_one(MessagePane).append_system(text)

    def clear_messages(self) -> None:
        self.query_one(MessagePane).clear()

    def cancel_chat(self) -> None:
        worker = self._chat_worker
        if worker is not None and worker.is_running:
            worker.cancel()

    def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        text = event.text
        if self._chat_busy:
            self.notify('Still processing — please wait', severity='warning', timeout=4)
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
