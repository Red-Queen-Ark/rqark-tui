from functools import cache
from importlib.metadata import PackageNotFoundError, version

from textual.reactive import reactive
from textual.widgets import Static


@cache
def _package_version(distribution: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return 'N/A'


class HeaderBar(Static):
    """Header: 'RQArk TUI vX | Core: <ver> App: <ver> | Agent: <name> | Model: <name> | Title: <session title>'."""

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
        title = '[#DC143C]RQArk TUI[/]'
        version_part = f'[#808080]v{_package_version("rqark-tui")}[/]'
        core = f'[#808080]Core:[/] [#808080]{_package_version("rqark-core")}[/]'
        app = f'[#808080]App:[/] [#808080]{_package_version("rqark-app")}[/]'
        agent = f'[#808080]Agent:[/] [#A020F0]{self.agent_name or "-"}[/]'
        model = f'[#808080]Model:[/] [#4FC1FF]{self.model_name or "-"}[/]'
        session = f'[#808080]Title:[/] [#e0e0e0]{self.session_title or "-"}[/]'
        return f'[b]{title} {version_part} | {core} {app} | {agent} | {model} | {session}[/b]'
