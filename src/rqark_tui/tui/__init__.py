from asyncio import AbstractEventLoop
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime

from rqark_app.types.session import SummaryMessage
from rqark_core.types.chat import AssistantMessage, Message, SystemMessage, ToolMessage, UserMessage
from rqark_core.types.tool import BaseTool
from textual.app import App, AutopilotCallbackType, ComposeResult
from textual.worker import Worker

from rqark_tui.tui.components.completion import CompletionPopup
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
        self._restore_messages: Sequence[Message | SummaryMessage] | None = None
        self._tool_keys: dict[str, str] = {}

    def set_tools(self, tools: Sequence[BaseTool]) -> None:
        self._tool_keys = {tool.name: tool.display_key for tool in tools}

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
        self.query_one(MessagePane).set_tool_keys(self._tool_keys)
        self.query_one(ChatInput).focus()
        self._replay_restored_messages()

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

    def restore_session(self, messages: Sequence[Message | SummaryMessage]) -> None:
        self._restore_messages = messages
        if self.is_running:
            self._replay_restored_messages()

    def _replay_restored_messages(self) -> None:
        messages, self._restore_messages = self._restore_messages, None
        if not messages:
            return
        for m in messages:
            at = getattr(m, 'created_at', None)
            if isinstance(m, (SummaryMessage, SystemMessage)):
                self.append_system(m.content, at)
            elif isinstance(m, UserMessage):
                self.append_message(m.content, at)
            elif isinstance(m, AssistantMessage):
                if m.reasoning_content:
                    self.append_think_delta(m.reasoning_content, at)
                if m.content:
                    self.append_agent_delta(m.content, at)
                if m.tool_calls:
                    for call in m.tool_calls:
                        self.append_tool_call(call.name, call.arguments, at)
                else:
                    self.close_agent_message()
            elif isinstance(m, ToolMessage):
                self.append_tool_result(m.tool_name or '', m.content, at)

    def append_message(self, text: str, at: datetime | None = None) -> None:
        self.query_one(MessagePane).append_message(text, at)

    def append_agent_delta(self, text: str, at: datetime | None = None) -> None:
        self.query_one(MessagePane).append_agent_delta(text, at)

    def append_think_delta(self, text: str, at: datetime | None = None) -> None:
        self.query_one(MessagePane).append_think_delta(text, at)

    def close_agent_message(self) -> None:
        self.query_one(MessagePane).close_agent_message()

    def append_tool_call(self, name: str, arguments: str = '', at: datetime | None = None) -> None:
        self.query_one(MessagePane).append_tool_call(name, arguments, at)

    def append_tool_result(self, name: str, content: str, at: datetime | None = None) -> None:
        self.query_one(MessagePane).append_tool_result(name, content, at)

    def append_error(self, text: str, at: datetime | None = None) -> None:
        self.query_one(MessagePane).append_error(text, at)

    def append_system(self, text: str, at: datetime | None = None) -> None:
        self.query_one(MessagePane).append_system(text, at)

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
        self.append_message(text)
        if self._chat_handler is None:
            return
        self._chat_busy = True
        self._chat_worker = self.run_worker(
            self._run_chat(text),
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
