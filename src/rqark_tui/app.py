from textual import events
from textual.app import App, ComposeResult

from rqark_tui._tui.footer import ChatInput
from rqark_tui._tui.header import HeaderBar
from rqark_tui._tui.main import MessagePane


class AgentTUI(App):
    ESCAPE_EXIT_COUNT = 3

    def __init__(self):
        super().__init__()
        self._escape_presses = 0
        self._agent_name = ''
        self._model_name = ''
        self._session_title = ''

    def compose(self) -> ComposeResult:
        yield HeaderBar()
        yield MessagePane()
        yield ChatInput()

    def on_mount(self) -> None:
        self.screen.styles.background = '#141414'

    def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        """Show a submitted message in the main pane."""
        self.query_one(MessagePane).append_message(event.text)

    def on_key(self, event: events.Key) -> None:
        if event.key == 'escape':
            self._escape_presses += 1
            if self._escape_presses >= self.ESCAPE_EXIT_COUNT:
                self.exit()
        else:
            self._escape_presses = 0

    def set_agent_name(self, name: str) -> None:
        self._agent_name = name
        self.query_one(HeaderBar).agent_name = name

    def set_model_name(self, name: str) -> None:
        self._model_name = name
        self.query_one(HeaderBar).model_name = name

    def set_session_title(self, title: str) -> None:
        self._session_title = title
        self.query_one(HeaderBar).session_title = title
