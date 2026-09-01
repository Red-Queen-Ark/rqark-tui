from textual.app import App, ComposeResult

from rqark_tui.tui.footer import ChatInput
from rqark_tui.tui.header import HeaderBar
from rqark_tui.tui.main import MessagePane
from rqark_tui.tui.quit_handler import QuitHandler


class AgentTUI(QuitHandler, App):
    """The rqark TUI: header bar, scrollable message pane and chat input."""

    def __init__(self):
        super().__init__()

    def compose(self) -> ComposeResult:
        yield HeaderBar()
        yield MessagePane()
        yield ChatInput()

    def on_mount(self) -> None:
        self.screen.styles.background = '#141414'

    def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        self.query_one(MessagePane).append_message(event.text)

    def set_agent_name(self, name: str) -> None:
        self.query_one(HeaderBar).agent_name = name

    def set_model_name(self, name: str) -> None:
        self.query_one(HeaderBar).model_name = name

    def set_session_title(self, title: str) -> None:
        self.query_one(HeaderBar).session_title = title
