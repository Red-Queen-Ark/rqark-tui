from importlib.metadata import PackageNotFoundError, version

from textual.reactive import reactive
from textual.widgets import Static


def _package_version() -> str:
    try:
        return version('rqark-tui')
    except PackageNotFoundError:
        return 'N/A'


class HeaderBar(Static):
    """Header: 'RQArk TUI vX | Agent: <name> | Model: <name> | Title: <session title>'."""

    agent_name = reactive('')
    model_name = reactive('')
    session_title = reactive('')

    DEFAULT_CSS = """
    HeaderBar {
        border: round #303030;
        height: 3;
        padding: 0 2;
        background: transparent;
        content-align: left middle;
        color: #808080;
    }
    """

    def __init__(self, agent_name: str = '', model_name: str = '', session_title: str = '') -> None:
        super().__init__()
        self.agent_name = agent_name
        self.model_name = model_name
        self.session_title = session_title

    def render(self) -> str:
        version_str = _package_version()
        title = '[#DC143C]RQArk TUI[/]'
        version_part = f'[#808080]v{version_str}[/]'
        agent = f'[#808080]Agent:[/] [#A020F0]{self.agent_name or "-"}[/]'
        model = f'[#808080]Model:[/] [#4FC1FF]{self.model_name or "-"}[/]'
        session = f'[#808080]Title:[/] [#e0e0e0]{self.session_title or "-"}[/]'
        return f'[b]{title} {version_part} | {agent} | {model} | {session}[/b]'
