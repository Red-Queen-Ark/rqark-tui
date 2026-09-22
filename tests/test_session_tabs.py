from textual.app import App, ComposeResult

from rqark_tui.tui.components.session import CLOSE_MARK, NEW_SESSION_TAB_ID, SessionTab, SessionTabs


class TabsApp(App[None]):
    def __init__(self) -> None:
        super().__init__()
        self.selected: list[str] = []
        self.new_requests = 0
        self.closes: list[str] = []

    def compose(self) -> ComposeResult:
        yield SessionTabs()

    def on_session_tabs_selected(self, event: SessionTabs.Selected) -> None:
        self.selected.append(event.key)

    def on_session_tabs_new_requested(self, event: SessionTabs.NewRequested) -> None:
        self.new_requests += 1

    def on_session_tabs_close_requested(self, event: SessionTabs.CloseRequested) -> None:
        self.closes.append(event.key)


def labels(tabs: SessionTabs) -> list[str]:
    """Tab labels without the close mark a session tab carries."""
    return [tab.label_text.removesuffix(CLOSE_MARK) for tab in tabs.query('Tab')]


async def test_the_plus_tab_is_the_only_tab_at_first():
    async with TabsApp().run_test(size=(60, 10)) as pilot:
        tabs = pilot.app.query_one(SessionTabs)
        await pilot.pause()
        assert labels(tabs) == ['+']
        assert tabs.tab_count == 1


async def test_add_session_keeps_the_plus_tab_last():
    async with TabsApp().run_test(size=(60, 10)) as pilot:
        tabs = pilot.app.query_one(SessionTabs)
        await pilot.pause()
        assert tabs.add_session('session-1', 'Session 1') == 'tab-session-1'
        assert tabs.add_session('session-2', 'Session 2') == 'tab-session-2'
        await pilot.pause()
        assert labels(tabs) == ['Session 1', 'Session 2', '+']
        assert tabs.tab_count == 3


async def test_activate_marks_a_session_tab_active():
    async with TabsApp().run_test(size=(60, 10)) as pilot:
        tabs = pilot.app.query_one(SessionTabs)
        await pilot.pause()
        tabs.add_session('session-1', 'Session 1')
        tabs.add_session('session-2', 'Session 2')
        tabs.activate('session-2')
        await pilot.pause()
        active = tabs.active_tab
        assert active is not None and active.id == 'tab-session-2'
        assert tabs.active == 'tab-session-2'
        tabs.activate('missing')
        assert tabs.active == 'tab-session-2'


async def test_set_label_renames_a_tab():
    async with TabsApp().run_test(size=(60, 10)) as pilot:
        tabs = pilot.app.query_one(SessionTabs)
        await pilot.pause()
        tabs.add_session('session-1', 'Session 1')
        await pilot.pause()
        tabs.set_label('session-1', 'titled')
        tabs.set_label('missing', 'ignored')
        assert labels(tabs) == ['titled', '+']


async def test_set_busy_toggles_the_marker_class():
    async with TabsApp().run_test(size=(60, 10)) as pilot:
        tabs = pilot.app.query_one(SessionTabs)
        await pilot.pause()
        tabs.add_session('session-1', 'Session 1')
        await pilot.pause()
        tab = tabs.get_tab('tab-session-1')
        assert tab is not None
        tabs.set_busy('session-1', True)
        assert tab.has_class('-busy')
        tabs.set_busy('session-1', False)
        assert not tab.has_class('-busy')


async def test_key_for_maps_a_tab_back_to_its_session():
    async with TabsApp().run_test(size=(60, 10)) as pilot:
        tabs = pilot.app.query_one(SessionTabs)
        await pilot.pause()
        tabs.add_session('session-1', 'Session 1')
        await pilot.pause()
        assert tabs.key_for(tabs.get_tab('tab-session-1')) == 'session-1'
        assert tabs.key_for(tabs.get_tab(NEW_SESSION_TAB_ID)) is None
        assert tabs.key_for(None) is None


async def test_clicking_a_session_tab_selects_it():
    async with TabsApp().run_test(size=(60, 10)) as pilot:
        tabs = pilot.app.query_one(SessionTabs)
        await pilot.pause()
        tabs.add_session('session-1', 'Session 1')
        tabs.add_session('session-2', 'Session 2')
        await pilot.pause()
        await pilot.click('#tab-session-1')
        assert pilot.app.selected == ['session-1']
        assert tabs.active == 'tab-session-1'
        await pilot.click('#tab-session-2')
        assert pilot.app.selected == ['session-1', 'session-2']
        assert tabs.active == 'tab-session-2'


async def test_clicking_the_plus_tab_asks_for_a_new_session_without_selecting_it():
    async with TabsApp().run_test(size=(60, 10)) as pilot:
        tabs = pilot.app.query_one(SessionTabs)
        await pilot.pause()
        tabs.add_session('session-1', 'Session 1')
        tabs.activate('session-1')
        await pilot.pause()
        await pilot.click('#new-session')
        assert pilot.app.new_requests == 1
        assert pilot.app.selected == []
        assert tabs.active == 'tab-session-1'


async def test_a_session_tab_carries_the_close_mark():
    async with TabsApp().run_test(size=(60, 10)) as pilot:
        tabs = pilot.app.query_one(SessionTabs)
        await pilot.pause()
        tabs.add_session('session-1', 'Session 1')
        await pilot.pause()
        tab = tabs.get_tab('tab-session-1')
        assert isinstance(tab, SessionTab)
        assert tab.label_text == f'Session 1{CLOSE_MARK}'


async def test_clicking_the_close_mark_asks_to_close_without_selecting():
    async with TabsApp().run_test(size=(60, 10)) as pilot:
        tabs = pilot.app.query_one(SessionTabs)
        await pilot.pause()
        tabs.add_session('session-1', 'Session 1')
        tabs.add_session('session-2', 'Session 2')
        tabs.activate('session-1')
        await pilot.pause()
        tab = tabs.get_tab('tab-session-2')
        await pilot.click('#tab-session-2', offset=(tab.content_size.width - 1, 0))
        await pilot.pause()
        assert pilot.app.closes == ['session-2']
        assert pilot.app.selected == []
        assert tabs.active == 'tab-session-1'


async def test_clicking_elsewhere_on_a_tab_still_selects_it():
    async with TabsApp().run_test(size=(60, 10)) as pilot:
        tabs = pilot.app.query_one(SessionTabs)
        await pilot.pause()
        tabs.add_session('session-1', 'Session 1')
        tabs.add_session('session-2', 'Session 2')
        await pilot.pause()
        tab = tabs.get_tab('tab-session-2')
        padding = 1  # Tab's own CSS pads the label by one cell on each side
        content = tab.size.width  # Widget.size is the content size
        mark_start = content - len(CLOSE_MARK) + padding
        close_offsets = (mark_start, content - 1 + padding)
        select_offsets = (0, padding, mark_start - 1, content + padding)
        for offset in close_offsets:
            pilot.app.closes.clear()
            await pilot.click('#tab-session-2', offset=(offset, 0))
            await pilot.pause()
            assert pilot.app.closes == ['session-2'], offset
        for offset in select_offsets:
            pilot.app.closes.clear()
            pilot.app.selected.clear()
            await pilot.click('#tab-session-2', offset=(offset, 0))
            await pilot.pause()
            assert pilot.app.closes == [], offset
            assert pilot.app.selected == ['session-2'], offset


async def test_removing_a_session_drops_its_tab_and_keeps_the_plus_last():
    async with TabsApp().run_test(size=(60, 10)) as pilot:
        tabs = pilot.app.query_one(SessionTabs)
        await pilot.pause()
        tabs.add_session('session-1', 'Session 1')
        tabs.add_session('session-2', 'Session 2')
        tabs.add_session('session-3', 'Session 3')
        await pilot.pause()
        tabs.remove_session('session-2')
        await pilot.pause()
        assert labels(tabs) == ['Session 1', 'Session 3', '+']
        assert tabs.tab_count == 3
        assert tabs.key_for(tabs.get_tab('tab-session-2')) is None
        tabs.remove_session('session-2')
        tabs.remove_session('missing')
        await pilot.pause()
        assert labels(tabs) == ['Session 1', 'Session 3', '+']


async def test_a_removed_session_tab_is_no_longer_selectable():
    async with TabsApp().run_test(size=(60, 10)) as pilot:
        tabs = pilot.app.query_one(SessionTabs)
        await pilot.pause()
        tabs.add_session('session-1', 'Session 1')
        tabs.add_session('session-2', 'Session 2')
        tabs.activate('session-2')
        await pilot.pause()
        tabs.remove_session('session-2')
        await pilot.pause()
        pilot.app.selected.clear()
        assert tabs.active != 'tab-session-2'
        assert labels(tabs) == ['Session 1', '+']
        assert pilot.app.closes == []
        assert pilot.app.selected == []


async def test_set_busy_and_set_label_ignore_removed_sessions():
    async with TabsApp().run_test(size=(60, 10)) as pilot:
        tabs = pilot.app.query_one(SessionTabs)
        await pilot.pause()
        tabs.add_session('session-1', 'Session 1')
        await pilot.pause()
        tabs.remove_session('session-1')
        await pilot.pause()
        tabs.set_busy('session-1', True)
        tabs.set_label('session-1', 'gone')
        tabs.activate('session-1')
        await pilot.pause()
        assert labels(tabs) == ['+']
