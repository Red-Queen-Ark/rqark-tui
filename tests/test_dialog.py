from textual.app import App
from textual.widgets import Button, Label

from rqark_tui.tui.components.dialog import YesNoDialog


class DialogApp(App[None]):
    def __init__(self, **kwargs) -> None:
        super().__init__()
        self.result: bool | None = None
        self._kwargs = kwargs

    def on_mount(self) -> None:
        self.push_screen(YesNoDialog('Delete this?', **self._kwargs), self._store)

    def _store(self, result: bool | None) -> None:
        self.result = result


async def test_dialog_renders_the_message_and_labels():
    app = DialogApp(title='Delete?', yes_label='Delete', no_label='Keep')
    async with app.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        assert str(app.screen.query_one(Label).render()) == 'Delete this?'
        assert app.screen.query_one('#yes', Button).label.plain == 'Delete'
        assert app.screen.query_one('#no', Button).label.plain == 'Keep'


async def test_yes_button_is_focused_by_default():
    app = DialogApp()
    async with app.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        assert app.screen.focused.id == 'yes'


async def test_no_button_is_focused_when_default_yes_is_false():
    app = DialogApp(default_yes=False)
    async with app.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        assert app.screen.focused.id == 'no'


async def test_enter_confirms_the_default_yes_button():
    app = DialogApp()
    async with app.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await pilot.press('enter')
        await pilot.pause()
        assert app.result is True


async def test_enter_declines_when_no_is_the_default():
    app = DialogApp(default_yes=False)
    async with app.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await pilot.press('enter')
        await pilot.pause()
        assert app.result is False


async def test_escape_declines():
    app = DialogApp()
    async with app.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await pilot.press('escape')
        await pilot.pause()
        assert app.result is False


async def test_ctrl_e_confirms():
    app = DialogApp()
    async with app.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await pilot.press('ctrl+e')
        await pilot.pause()
        assert app.result is True


async def test_clicking_the_no_button_declines():
    app = DialogApp()
    async with app.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        app.screen.query_one('#no', Button).press()
        await pilot.pause()
        assert app.result is False


async def test_clicking_the_yes_button_confirms():
    app = DialogApp()
    async with app.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        app.screen.query_one('#yes', Button).press()
        await pilot.pause()
        assert app.result is True


async def test_left_and_right_move_the_focus_between_the_buttons():
    app = DialogApp()
    async with app.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await pilot.press('right')
        assert app.screen.focused.id == 'no'
        await pilot.press('left')
        assert app.screen.focused.id == 'yes'


async def test_dialog_border_shows_the_title_and_hint():
    app = DialogApp(title='Quit?')
    async with app.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        container = app.screen.query_one('#dialog')
        assert container.border_title == 'Quit?'
        assert 'Esc to cancel' in container.border_subtitle
