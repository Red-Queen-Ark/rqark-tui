from functools import cache
from importlib.metadata import PackageNotFoundError, version

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Static

from rqark_tui.tui.theme import active_theme


def _colour(token: str) -> str:
    """The active theme's value for ``token``."""
    return active_theme().color(token)


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
        border: round;
        height: 3;
        padding: 0 2;
        background: transparent;
    }
    HeaderBar > .header-line {
        width: 1fr;
        height: 1;
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
        yield Static(f'[b {_colour("accent")}]Cloud[/]', classes='header-cloud')

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
        accent = _colour('accent')
        agent = _colour('agent')
        title = f'[{_colour("user")}]RQArk TUI[/]'
        muted = _colour('fg_muted')
        version_part = f'[{muted}]v{_package_version("rqark-tui")}[/]'
        core = f'[{muted}]Core:[/] [{muted}]{_package_version("rqark-core")}[/]'
        app = f'[{muted}]App:[/] [{muted}]{_package_version("rqark-app")}[/]'
        agent_part = f'[{muted}]Agent:[/] [{agent}]{self.agent_name or "-"}[/]'
        model = f'[{muted}]Model:[/] [{accent}]{self.model_name or "-"}[/]'
        return f'[b]{title} {version_part} | {core} {app} | {agent_part} | {model}[/b]'
