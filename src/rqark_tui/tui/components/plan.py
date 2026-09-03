from rich.markup import escape
from rqark_core.types.tool import PlanItem
from textual.widgets import Static

MAX_VISIBLE = 10

_STATUS_COLORS = {
    'pending': '#808080',
    'in_progress': '#4FC1FF',
    'completed': '#2E8B57',
    'cancelled': '#555555',
}


class PlanPanel(Static):
    """Shows the current session plan above the chat input."""

    DEFAULT_CSS = """
    PlanPanel {
        display: none;
        border: round #303030;
        background: #1a1a1a;
        padding: 0 2;
        height: auto;
        color: #808080;
    }
    """

    def __init__(self) -> None:
        super().__init__('')
        self._items: list[PlanItem] = []

    def set_plan(self, items: list[PlanItem]) -> None:
        self._items = list(items)
        self.display = bool(self._items)
        self.refresh()

    def render(self) -> str:
        items = self._items
        if not items:
            return ''
        lines = ['[b][#808080]Session Plan[/][/]']
        for item in items[:MAX_VISIBLE]:
            color = _STATUS_COLORS.get(item.status, '#808080')
            lines.append(f'[{color}]{item.icon} {escape(item.content)}[/]')
        if len(items) > MAX_VISIBLE:
            lines.append(f'[#808080]… +{len(items) - MAX_VISIBLE} more[/]')
        return '\n'.join(lines)
