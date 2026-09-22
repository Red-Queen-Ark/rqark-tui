from rich.style import Style
from rich.text import Text
from textual import events
from textual.await_complete import AwaitComplete
from textual.message import Message
from textual.widgets import Tab, Tabs

NEW_SESSION_TAB_ID = 'new-session'

#: The close affordance appended to a session tab's label.
CLOSE_MARK = ' ×'


class SessionTab(Tab):
    """A session tab whose label ends in a clickable ``×``.

    ``Tab`` does not dispatch per-cell ``@click`` metadata and its own ``_on_click``
    cannot be suppressed, so the click is remembered here and consumed by
    :meth:`SessionTabs._activate_tab`: the ``×`` asks for a close, anything else
    behaves like a normal tab click.
    """

    def __init__(self, title: str, *, id: str | None = None, classes: str = '') -> None:
        super().__init__(self._labelled(title), id=id, classes=classes)
        self._close_clicked = False

    def set_title(self, title: str) -> None:
        """Rename the tab, keeping the close mark."""
        self.label = self._labelled(title)

    @staticmethod
    def _labelled(title: str) -> Text:
        return Text.assemble((title, Style()), (CLOSE_MARK, Style(color='#808080')))

    def take_close_click(self) -> bool:
        """True when the last click landed on the close mark (and clears the flag)."""
        clicked, self._close_clicked = self._close_clicked, False
        return clicked

    def _on_click(self, event: events.Click | None = None) -> None:
        offset = event.get_content_offset(self) if event is not None else None
        self._close_clicked = offset is not None and offset.x >= self.content_size.width - len(CLOSE_MARK)


class SessionTabs(Tabs):
    """Tab strip with one tab per chat session and a trailing ``+`` for a new one.

    Activating a session tab posts :class:`SessionTabs.Selected`; activating ``+``
    posts :class:`SessionTabs.NewRequested` and leaves the current tab in place;
    clicking a tab's ``×`` posts :class:`SessionTabs.CloseRequested` instead of
    selecting it. Busy sessions mark their tab with ``-busy`` so a running chat is
    obvious while another one is on screen.
    """

    DEFAULT_CSS = """
    SessionTabs {
        height: 4;
        border: round #303030;
        padding: 0 2;
        background: transparent;

        & Tab {
            color: #808080;
            background: transparent;

            &:hover {
                color: #e0e0e0;
            }

            &.-busy {
                color: #FFD700;
                text-style: bold;
            }

            &.-active {
                color: #4FC1FF;
                text-style: bold;
            }

            &.-add {
                color: #4FC1FF;
            }
        }
    }
    """

    class Selected(Message):
        """Posted when a session tab is activated."""

        def __init__(self, tabs: 'SessionTabs', key: str) -> None:
            super().__init__()
            self.tabs = tabs
            self.key = key

        @property
        def control(self) -> 'SessionTabs':
            return self.tabs

    class NewRequested(Message):
        """Posted when the ``+`` tab is activated."""

        def __init__(self, tabs: 'SessionTabs') -> None:
            super().__init__()
            self.tabs = tabs

        @property
        def control(self) -> 'SessionTabs':
            return self.tabs

    class CloseRequested(Message):
        """Posted when a session tab's close mark is clicked."""

        def __init__(self, tabs: 'SessionTabs', key: str) -> None:
            super().__init__()
            self.tabs = tabs
            self.key = key

        @property
        def control(self) -> 'SessionTabs':
            return self.tabs

    def __init__(self) -> None:
        super().__init__(Tab('+', id=NEW_SESSION_TAB_ID, classes='-add'), id='session-tabs')
        self._keys_by_tab: dict[str, str] = {}
        self._tabs_by_key: dict[str, str] = {}

    def add_session(self, key: str, label: str) -> str:
        """Append a tab for ``key``, keeping the ``+`` tab last."""
        tab_id = f'tab-{key}'
        self._keys_by_tab[tab_id] = key
        self._tabs_by_key[key] = tab_id
        self.add_tab(SessionTab(label, id=tab_id), before=NEW_SESSION_TAB_ID)
        return tab_id

    def remove_session(self, key: str) -> AwaitComplete:
        """Drop a session's tab; the ``+`` tab always stays.

        Returns the pending removal, so a caller that must re-select a tab afterwards
        (``Tabs`` falls back to ``+`` when the active tab goes) can await it first.
        """
        tab_id = self._tabs_by_key.pop(key, None)
        if tab_id is None:
            return AwaitComplete()
        self._keys_by_tab.pop(tab_id, None)
        return self.remove_tab(tab_id)

    def activate(self, key: str) -> None:
        """Mark ``key``'s tab as the active one."""
        tab_id = self._tabs_by_key.get(key)
        if tab_id is not None:
            self.active = tab_id

    def set_label(self, key: str, label: str) -> None:
        tab = self._tab(key)
        if isinstance(tab, SessionTab):
            tab.set_title(label)

    def set_busy(self, key: str, busy: bool) -> None:
        tab = self._tab(key)
        if tab is not None:
            tab.set_class(busy, '-busy')

    def key_for(self, tab: Tab | None) -> str | None:
        """The session key behind ``tab``, or None for the ``+`` tab."""
        if tab is None or tab.id is None:
            return None
        return self._keys_by_tab.get(tab.id)

    def _tab(self, key: str) -> Tab | None:
        tab_id = self._tabs_by_key.get(key)
        return self.get_tab(tab_id) if tab_id is not None else None

    def _activate_tab(self, tab: Tab) -> None:
        """Activate a session tab, or close it when its ``×`` was clicked.

        A click on ``+`` only asks for a new session; a click on a session tab's
        close mark asks for that session to be removed, without selecting it.
        """
        if tab.id == NEW_SESSION_TAB_ID:
            self.post_message(self.NewRequested(self))
            return
        if isinstance(tab, SessionTab) and tab.take_close_click():
            key = self.key_for(tab)
            if key is not None:
                self.post_message(self.CloseRequested(self, key))
            return
        super()._activate_tab(tab)
        key = self.key_for(tab)
        if key is not None:
            self.post_message(self.Selected(self, key))
