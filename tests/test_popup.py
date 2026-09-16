from rich.markup import escape
from textual.app import App, ComposeResult

from rqark_tui.tui.components.popup import MAX_VISIBLE, PopupSelector

ENTRIES = [(f'item{i}', str(i)) for i in range(8)]


class PopupApp(App[None]):
    def compose(self) -> ComposeResult:
        yield PopupSelector('default title')


async def test_show_displays_the_entries_and_highlights_the_index():
    app = PopupApp()
    async with app.run_test(size=(40, 100)) as pilot:
        popup = app.query_one(PopupSelector)
        await pilot.pause()
        popup.show(ENTRIES, title='Pick', index=2)
        assert popup.display is True
        assert popup.selectable is True
        assert popup.selected_entry == ('item2', '2')
        assert popup.border_title == 'Pick'
        assert popup.render().splitlines()[0] == '  item0'
        assert '❯ item2' in popup.render()


async def test_show_clamps_the_index_to_the_entry_range():
    app = PopupApp()
    async with app.run_test(size=(40, 100)) as pilot:
        popup = app.query_one(PopupSelector)
        await pilot.pause()
        popup.show(ENTRIES, index=99)
        assert popup.selected_entry == ('item7', '7')
        popup.show(ENTRIES, index=-5)
        assert popup.selected_entry == ('item0', '0')


async def test_show_with_no_entries_hides_the_popup():
    app = PopupApp()
    async with app.run_test(size=(40, 100)) as pilot:
        popup = app.query_one(PopupSelector)
        await pilot.pause()
        popup.show([])
        assert popup.display is False
        assert popup.render() == ''


async def test_move_clamps_at_both_ends():
    app = PopupApp()
    async with app.run_test(size=(40, 100)) as pilot:
        popup = app.query_one(PopupSelector)
        await pilot.pause()
        popup.show(ENTRIES)
        popup.move(-1)
        assert popup.selected_entry == ('item0', '0')
        popup.move(3)
        assert popup.selected_entry == ('item3', '3')
        popup.move(100)
        assert popup.selected_entry == ('item7', '7')


async def test_move_does_nothing_without_entries():
    app = PopupApp()
    async with app.run_test(size=(40, 100)) as pilot:
        popup = app.query_one(PopupSelector)
        await pilot.pause()
        popup.move(1)
        assert popup.selected_entry is None
        assert popup.render() == ''


async def test_counter_subtitle_tracks_the_selection():
    app = PopupApp()
    async with app.run_test(size=(40, 100)) as pilot:
        popup = app.query_one(PopupSelector)
        await pilot.pause()
        popup.show(ENTRIES)
        assert popup.border_subtitle == '1/8'
        popup.move(2)
        assert popup.border_subtitle == '3/8'


async def test_counter_subtitle_is_empty_when_everything_fits():
    app = PopupApp()
    async with app.run_test(size=(40, 100)) as pilot:
        popup = app.query_one(PopupSelector)
        await pilot.pause()
        popup.show(ENTRIES[:MAX_VISIBLE])
        assert popup.border_subtitle == ''


async def test_scrolling_window_follows_the_selection():
    app = PopupApp()
    async with app.run_test(size=(40, 100)) as pilot:
        popup = app.query_one(PopupSelector)
        await pilot.pause()
        popup.show(ENTRIES, index=MAX_VISIBLE + 1)
        lines = popup.render().splitlines()
        assert len(lines) == MAX_VISIBLE
        assert '❯ item7' in lines
        assert popup.border_subtitle == '8/8'


async def test_hide_resets_everything():
    app = PopupApp()
    async with app.run_test(size=(40, 100)) as pilot:
        popup = app.query_one(PopupSelector)
        await pilot.pause()
        popup.show(ENTRIES, index=3)
        popup.hide()
        assert popup.display is False
        assert popup.selected_entry is None
        assert popup.selectable is True
        assert popup.border_subtitle == ''
        assert popup.render() == ''


async def test_show_text_switches_to_a_read_only_view():
    app = PopupApp()
    async with app.run_test(size=(40, 100)) as pilot:
        popup = app.query_one(PopupSelector)
        await pilot.pause()
        popup.show_text('first\nsecond', title='Plan')
        assert popup.display is True
        assert popup.selectable is False
        assert popup.selected_entry is None
        assert popup.border_title == 'Plan'
        assert popup.render() == '  first\n  second'


async def test_show_text_escapes_markup():
    app = PopupApp()
    async with app.run_test(size=(40, 100)) as pilot:
        popup = app.query_one(PopupSelector)
        await pilot.pause()
        popup.show_text('[b]not markup[/b]')
        assert popup.render() == f'  {escape("[b]not markup[/b]")}'


async def test_show_text_with_blank_input_hides_the_popup():
    app = PopupApp()
    async with app.run_test(size=(40, 100)) as pilot:
        popup = app.query_one(PopupSelector)
        await pilot.pause()
        popup.show(ENTRIES)
        popup.show_text('')
        assert popup.display is False


async def test_display_mode_counter_tracks_the_scroll_window():
    app = PopupApp()
    async with app.run_test(size=(40, 100)) as pilot:
        popup = app.query_one(PopupSelector)
        await pilot.pause()
        popup.show_text('\n'.join(f'line{i}' for i in range(10)))
        assert popup.border_subtitle == f'1–{MAX_VISIBLE}/10'
        popup.move(2)
        assert popup.border_subtitle == f'3–{MAX_VISIBLE + 2}/10'


async def test_display_mode_scrolling_clamps_at_the_end():
    app = PopupApp()
    async with app.run_test(size=(40, 100)) as pilot:
        popup = app.query_one(PopupSelector)
        await pilot.pause()
        popup.show_text('\n'.join(f'line{i}' for i in range(10)))
        popup.move(100)
        assert popup.border_subtitle == '5–10/10'
        assert popup.render().splitlines()[-1] == '  line9'


async def test_show_after_show_text_switches_back_to_a_selector():
    app = PopupApp()
    async with app.run_test(size=(40, 100)) as pilot:
        popup = app.query_one(PopupSelector)
        await pilot.pause()
        popup.show_text('plan')
        popup.show(ENTRIES)
        assert popup.selectable is True
        assert popup.selected_entry == ('item0', '0')


async def test_default_title_is_used_when_the_title_is_none():
    app = PopupApp()
    async with app.run_test(size=(40, 100)) as pilot:
        popup = app.query_one(PopupSelector)
        await pilot.pause()
        popup.show(ENTRIES, title='Other')
        popup.show(ENTRIES, title=None)
        assert popup.border_title == 'default title'
