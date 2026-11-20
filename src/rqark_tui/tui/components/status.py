from functools import cache
from importlib.metadata import PackageNotFoundError, version

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.css.query import NoMatches
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


class StatusBar(Horizontal):
    """The line under the input: 'RQArk TUI vX | Core: <ver> App: <ver> | Agent: <name> | Model: <name>'.

    The line sits on the left; in cloud mode a 'Cloud' badge is shown on the far right.
    """

    agent_name = reactive('')
    model_name = reactive('')
    cloud = reactive(False)

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        margin: 0 0 1 0;
        padding: 0 3;
        background: transparent;
    }
    StatusBar > .status-line {
        width: 1fr;
        height: 1;
    }
    StatusBar > .status-cloud {
        width: auto;
        height: 1;
        display: none;
    }
    StatusBar.cloud > .status-cloud {
        display: block;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static('', classes='status-line')
        yield Static(f'[b {_colour("accent")}]Cloud[/]', classes='status-cloud')

    def on_mount(self) -> None:
        self._update_line()

    def watch_agent_name(self, _name: str) -> None:
        self._update_line()

    def watch_model_name(self, _name: str) -> None:
        self._update_line()

    def watch_cloud(self, cloud: bool) -> None:
        self.set_class(cloud, 'cloud')

    def repaint(self) -> None:
        """Repaint the line and the badge after the theme changed."""
        try:
            badge = self.query_one('.status-cloud', Static)
        except NoMatches:
            return
        badge.update(f'[b {_colour("accent")}]Cloud[/]')
        self._update_line()

    def _update_line(self) -> None:
        try:
            self.query_one('.status-line', Static).update(self._line())
        except NoMatches:
            # Before the children are composed there is nothing to write to.
            pass

    def _line(self) -> str:
        """Agent and model first, versions last: a narrow window loses the versions."""
        accent = _colour('accent')
        agent = _colour('agent')
        muted = _colour('fg_muted')
        agent_part = f'[{muted}]Agent:[/] [{agent}]{escape(self.agent_name or "-")}[/]'
        model = f'[{muted}]Model:[/] [{accent}]{escape(self.model_name or "-")}[/]'
        versions = f'[{muted}]v{_package_version("rqark-tui")} · core {_package_version("rqark-core")} · app {_package_version("rqark-app")}[/]'
        return f'[b]{agent_part} | {model}  {versions}[/b]'
