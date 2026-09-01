from textual.widgets import RichLog


class MessagePane(RichLog):
    """Scrollable message area showing the submitted messages."""

    DEFAULT_CSS = """
    MessagePane {
        height: 1fr;
        border: round #303030;
        padding: 1 2;
        background: #141414;
    }
    MessagePane:focus {
        background-tint: transparent;
        border: round #303030;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._message_count = 0

    def append_message(self, text: str) -> None:
        """Append a submitted message to the pane."""
        self._message_count += 1
        self.write(f'[bold #DC143C]you[/] [dim]#{self._message_count}[/]\n{text}')
        self.scroll_end(animate=False)
