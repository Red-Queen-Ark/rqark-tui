from functools import cache
from importlib.metadata import PackageNotFoundError, version

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Static


@cache
def _package_version(distribution: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return 'N/A'


class HeaderBar(Horizontal):
    """Header: 'RQArk TUI vX | Core: <ver> App: <ver> | Agent: <name> | Model: <name>'.

    The line sits on the left; in cloud mode a 'Cloud' badge is shown on the far right.
    """

    agent_name = reactive('')
    model_name = reactive('')
    cloud = reactive(False)

    DEFAULT_CSS = """
    HeaderBar {
        border: round #303030;
        height: 3;
        padding: 0 2;
        background: transparent;
        color: #808080;
    }
    HeaderBar > .header-line {
        width: 1fr;
        height: 1;
        color: #808080;
    }
    HeaderBar > .header-cloud {
        width: auto;
        height: 1;
        display: none;
    }
    HeaderBar.cloud > .header-cloud {
        display: block;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static('', classes='header-line')
        yield Static('[b #4FC1FF]Cloud[/]', classes='header-cloud')

    def on_mount(self) -> None:
        self._update_line()

    def watch_agent_name(self, _name: str) -> None:
        self._update_line()

    def watch_model_name(self, _name: str) -> None:
        self._update_line()

    def watch_cloud(self, cloud: bool) -> None:
        self.set_class(cloud, 'cloud')

    def _update_line(self) -> None:
        if self.is_mounted:
            self.query_one('.header-line', Static).update(self._line())

    def _line(self) -> str:
        title = '[#DC143C]RQArk TUI[/]'
        version_part = f'[#808080]v{_package_version("rqark-tui")}[/]'
        core = f'[#808080]Core:[/] [#808080]{_package_version("rqark-core")}[/]'
        app = f'[#808080]App:[/] [#808080]{_package_version("rqark-app")}[/]'
        agent = f'[#808080]Agent:[/] [#A020F0]{self.agent_name or "-"}[/]'
        model = f'[#808080]Model:[/] [#4FC1FF]{self.model_name or "-"}[/]'
        return f'[b]{title} {version_part} | {core} {app} | {agent} | {model}[/b]'
