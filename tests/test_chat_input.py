from pathlib import Path

import pytest
from textual.app import App, ComposeResult

from rqark_tui.tui.components import footer as footer_module
from rqark_tui.tui.components import main as main_module
from rqark_tui.tui.components.footer import ChatInput
from rqark_tui.tui.components.main import MessagePane
from rqark_tui.tui.components.popup import PopupSelector


class InputApp(App[None]):
    AUTO_FOCUS = 'ChatInput'

    def __init__(self) -> None:
        super().__init__()
        self.submitted: list[str] = []
        self.attached: list[list[str]] = []

    def compose(self) -> ComposeResult:
        yield MessagePane()
        yield PopupSelector()
        yield ChatInput()

    def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        self.submitted.append(event.text)
        self.attached.append(event.images)


async def type_text(pilot, chat: ChatInput, text: str) -> None:
    chat.text = ''
    for char in text:
        await pilot.press(char)
    await pilot.pause()


def hold_shift(monkeypatch: pytest.MonkeyPatch, held: bool) -> None:
    monkeypatch.setattr(footer_module, '_is_shift_pressed', lambda: held)


def hold_ctrl(monkeypatch: pytest.MonkeyPatch, held: bool) -> None:
    monkeypatch.setattr(footer_module, '_is_ctrl_pressed', lambda: held)


def hold_return(monkeypatch: pytest.MonkeyPatch, held: bool) -> None:
    monkeypatch.setattr(footer_module, '_is_return_pressed', lambda: held)


def fake_matches(entries: list[tuple[str, str, bool]]):
    return lambda self, prefix: entries


async def test_enter_submits_and_clears_the_input():
    app = InputApp()
    async with app.run_test(size=(40, 100)) as pilot:
        chat = app.query_one(ChatInput)
        await pilot.pause()
        chat.text = 'hello'
        await pilot.press('enter')
        await pilot.pause()
        assert app.submitted == ['hello']
        assert chat.text == ''


async def test_shift_enter_inserts_a_newline(monkeypatch):
    hold_shift(monkeypatch, True)
    app = InputApp()
    async with app.run_test(size=(40, 100)) as pilot:
        chat = app.query_one(ChatInput)
        await pilot.pause()
        await type_text(pilot, chat, 'line one')
        await pilot.press('enter')
        await pilot.pause()
        assert app.submitted == []
        assert chat.text == 'line one\n'


async def test_ctrl_enter_inserts_a_newline(monkeypatch):
    hold_ctrl(monkeypatch, True)
    app = InputApp()
    async with app.run_test(size=(40, 100)) as pilot:
        chat = app.query_one(ChatInput)
        await pilot.pause()
        await type_text(pilot, chat, 'line one')
        await pilot.press('enter')
        await pilot.pause()
        assert app.submitted == []
        assert chat.text == 'line one\n'


async def test_plain_enter_submits_when_no_modifier_is_held():
    app = InputApp()
    async with app.run_test(size=(40, 100)) as pilot:
        chat = app.query_one(ChatInput)
        await pilot.pause()
        chat.text = 'plain'
        await pilot.press('enter')
        await pilot.pause()
        assert app.submitted == ['plain']


async def test_shift_enter_key_name_inserts_a_newline():
    app = InputApp()
    async with app.run_test(size=(40, 100)) as pilot:
        chat = app.query_one(ChatInput)
        await pilot.pause()
        await type_text(pilot, chat, 'line one')
        await pilot.press('shift+enter')
        await pilot.pause()
        assert app.submitted == []
        assert chat.text == 'line one\n'


async def test_ctrl_j_inserts_a_newline():
    app = InputApp()
    async with app.run_test(size=(40, 100)) as pilot:
        chat = app.query_one(ChatInput)
        await pilot.pause()
        await type_text(pilot, chat, 'line one')
        await pilot.press('ctrl+j')
        await pilot.pause()
        assert app.submitted == []
        assert chat.text == 'line one\n'


async def test_submit_strips_surrounding_newlines():
    app = InputApp()
    async with app.run_test(size=(40, 100)) as pilot:
        chat = app.query_one(ChatInput)
        await pilot.pause()
        chat.text = '\n\nbody\n\n'
        await pilot.press('enter')
        await pilot.pause()
        assert app.submitted == ['body']


async def test_submit_ignores_input_made_only_of_newlines():
    app = InputApp()
    async with app.run_test(size=(40, 100)) as pilot:
        chat = app.query_one(ChatInput)
        await pilot.pause()
        chat.text = '\n\n'
        await pilot.press('enter')
        await pilot.pause()
        assert app.submitted == []
        assert chat.text == '\n\n'


@pytest.mark.parametrize(('lines', 'height'), [(1, 3), (2, 4), (5, 7), (10, 12), (25, 12)])
async def test_input_height_grows_up_to_the_maximum(lines, height):
    app = InputApp()
    async with app.run_test(size=(40, 100)) as pilot:
        chat = app.query_one(ChatInput)
        await pilot.pause()
        chat.text = '\n'.join('x' for _ in range(lines))
        await pilot.pause()
        assert chat.styles.height is not None
        assert chat.styles.height.value == height


async def test_slash_prefix_opens_the_command_popup():
    app = InputApp()
    async with app.run_test(size=(40, 100)) as pilot:
        chat = app.query_one(ChatInput)
        popup = app.query_one(PopupSelector)
        await pilot.pause()
        chat.text = '/'
        await pilot.pause()
        assert popup.display is True
        assert [entry[1] for entry in popup._entries] == ['/clear', '/close', '/compact', '/new', '/stop', '/models', '/agents']
        assert chat.popup_active is True


async def test_typing_a_prefix_filters_command_entries():
    app = InputApp()
    async with app.run_test(size=(40, 100)) as pilot:
        chat = app.query_one(ChatInput)
        popup = app.query_one(PopupSelector)
        await pilot.pause()
        await type_text(pilot, chat, '/c')
        assert [entry[1] for entry in popup._entries] == ['/clear', '/close', '/compact']
        assert popup.display is True


async def test_unknown_slash_command_shows_no_completion():
    app = InputApp()
    async with app.run_test(size=(40, 100)) as pilot:
        chat = app.query_one(ChatInput)
        popup = app.query_one(PopupSelector)
        await pilot.pause()
        await type_text(pilot, chat, '/x')
        assert popup._entries == []
        assert popup.display is False


async def test_enter_on_the_command_popup_submits_the_selected_command():
    app = InputApp()
    async with app.run_test(size=(40, 100)) as pilot:
        chat = app.query_one(ChatInput)
        await pilot.pause()
        await type_text(pilot, chat, '/c')
        await pilot.press('enter')
        await pilot.pause()
        assert app.submitted == ['/clear']
        assert chat.text == ''


async def test_arrow_keys_move_the_command_highlight():
    app = InputApp()
    async with app.run_test(size=(40, 100)) as pilot:
        chat = app.query_one(ChatInput)
        popup = app.query_one(PopupSelector)
        await pilot.pause()
        await type_text(pilot, chat, '/')
        await pilot.press('down')
        assert popup.selected_entry == ('/close   Close this session', '/close')
        await pilot.press('up')
        assert popup.selected_entry == ('/clear   Clear the current conversation', '/clear')


async def test_escape_hides_the_command_popup():
    app = InputApp()
    async with app.run_test(size=(40, 100)) as pilot:
        chat = app.query_one(ChatInput)
        popup = app.query_one(PopupSelector)
        await pilot.pause()
        await type_text(pilot, chat, '/')
        await pilot.press('escape')
        await pilot.pause()
        assert popup.display is False
        assert chat.text == '/'


async def test_multiline_input_keeps_the_command_popup_closed():
    app = InputApp()
    async with app.run_test(size=(40, 100)) as pilot:
        chat = app.query_one(ChatInput)
        popup = app.query_one(PopupSelector)
        await pilot.pause()
        chat.text = '/clear\nmore'
        chat.cursor_location = (1, 4)
        await pilot.pause()
        assert popup.display is False


async def test_at_prefix_opens_file_completion(monkeypatch):
    monkeypatch.setattr(footer_module.FileMatcher, 'matches', fake_matches([('src/', 'src/', True), ('main.py', 'main.py', False)]))
    app = InputApp()
    async with app.run_test(size=(40, 100)) as pilot:
        chat = app.query_one(ChatInput)
        popup = app.query_one(PopupSelector)
        await pilot.pause()
        await type_text(pilot, chat, 'look at @')
        assert popup.display is True
        assert [entry[1] for entry in popup._entries] == ['src/', 'main.py']


async def test_at_completion_replaces_the_token_and_appends_a_space(monkeypatch):
    monkeypatch.setattr(footer_module.FileMatcher, 'matches', fake_matches([('main.py', 'main.py', False)]))
    app = InputApp()
    async with app.run_test(size=(40, 100)) as pilot:
        chat = app.query_one(ChatInput)
        await pilot.pause()
        await type_text(pilot, chat, 'look at @ma')
        await pilot.press('enter')
        await pilot.pause()
        assert chat.text == 'look at @main.py '
        assert app.submitted == []


async def test_at_inside_a_word_does_not_open_completion(monkeypatch):
    monkeypatch.setattr(footer_module.FileMatcher, 'matches', fake_matches([('main.py', 'main.py', False)]))
    app = InputApp()
    async with app.run_test(size=(40, 100)) as pilot:
        chat = app.query_one(ChatInput)
        popup = app.query_one(PopupSelector)
        await pilot.pause()
        await type_text(pilot, chat, 'mail@example')
        assert popup.display is False


@pytest.mark.parametrize(
    ('text', 'cursor', 'expected'),
    [
        ('@', (0, 1), ('', 0, False)),
        ('@ma', (0, 3), ('ma', 0, False)),
        ('see @ma', (0, 7), ('ma', 4, False)),
        ('see @ma no', (0, 7), ('ma', 4, False)),
        ('@!', (0, 2), ('', 0, True)),
        ('@!ma', (0, 4), ('ma', 0, True)),
        ('see @!ma', (0, 8), ('ma', 4, True)),
        ('mail@example', (0, 12), ('', None, False)),
        ('see @a b', (0, 8), ('', None, False)),
        ('plain', (0, 5), ('', None, False)),
    ],
)
async def test_file_prefix_detection(text, cursor, expected):
    app = InputApp()
    async with app.run_test(size=(40, 100)) as pilot:
        chat = app.query_one(ChatInput)
        await pilot.pause()
        chat.text = text
        chat.cursor_location = cursor
        await pilot.pause()
        assert chat._file_prefix() == expected


async def test_popup_active_is_false_for_a_read_only_popup():
    app = InputApp()
    async with app.run_test(size=(40, 100)) as pilot:
        chat = app.query_one(ChatInput)
        popup = app.query_one(PopupSelector)
        await pilot.pause()
        popup.show_text('plan line')
        assert chat.popup_active is False


async def test_begin_pick_without_entries_finishes_immediately():
    app = InputApp()
    async with app.run_test(size=(40, 100)) as pilot:
        chat = app.query_one(ChatInput)
        await pilot.pause()
        results: list[object] = []
        chat.begin_pick([], on_done=results.append)
        assert results == [None]


async def test_pick_mode_resolves_the_callback_and_clears_the_input():
    app = InputApp()
    async with app.run_test(size=(40, 100)) as pilot:
        chat = app.query_one(ChatInput)
        popup = app.query_one(PopupSelector)
        await pilot.pause()
        results: list[object] = []
        chat.text = 'draft'
        chat.begin_pick([('one', '1'), ('two', '2')], title='Pick', on_done=results.append)
        assert popup.display is True
        await pilot.press('down')
        await pilot.press('enter')
        await pilot.pause()
        assert results == [('two', '2')]
        assert chat.text == ''
        assert popup.display is False


async def test_pick_mode_escape_resolves_with_none():
    app = InputApp()
    async with app.run_test(size=(40, 100)) as pilot:
        chat = app.query_one(ChatInput)
        await pilot.pause()
        results: list[object] = []
        chat.begin_pick([('one', '1')], on_done=results.append)
        await pilot.press('escape')
        await pilot.pause()
        assert results == [None]


async def test_pick_mode_ignores_completion_updates():
    app = InputApp()
    async with app.run_test(size=(40, 100)) as pilot:
        chat = app.query_one(ChatInput)
        popup = app.query_one(PopupSelector)
        await pilot.pause()
        chat.begin_pick([('one', '1')], title='Pick', on_done=lambda entry: None)
        chat.text = '/clear'
        await pilot.pause()
        assert popup.selectable is True
        assert popup.selected_entry == ('one', '1')


async def test_ctrl_c_without_input_selection_copies_the_pane_selection(monkeypatch):
    copied: list[str] = []
    monkeypatch.setattr(main_module, 'write_system_clipboard', copied.append)
    app = InputApp()
    async with app.run_test(size=(30, 60)) as pilot:
        chat = app.query_one(ChatInput)
        pane = app.query_one(MessagePane)
        await pilot.pause()
        pane.append_message('abcdefghij')
        pane._selection_start = (1, 0)
        pane._selection_end = (1, 4)
        chat.focus()
        await pilot.press('ctrl+c')
        await pilot.pause()
        assert copied == ['abcd']
        assert app._exit is False


async def test_phantom_caret_is_dropped_while_return_is_held(monkeypatch):
    hold_return(monkeypatch, True)
    app = InputApp()
    async with app.run_test(size=(40, 100)) as pilot:
        chat = app.query_one(ChatInput)
        await pilot.pause()
        chat.text = 'body'
        await pilot.press('^')
        await pilot.pause()
        assert chat.text == 'body'
        assert app.submitted == []


async def test_genuine_caret_is_typed_when_return_is_not_held(monkeypatch):
    hold_return(monkeypatch, False)
    app = InputApp()
    async with app.run_test(size=(40, 100)) as pilot:
        chat = app.query_one(ChatInput)
        await pilot.pause()
        await pilot.press('^')
        await pilot.pause()
        assert chat.text == '^'


async def test_input_query_is_dropped_when_the_popup_is_missing():
    app = InputApp()
    async with app.run_test(size=(40, 100)) as pilot:
        chat = app.query_one(ChatInput)
        await pilot.pause()
        chat._popup = None
        app.query_one(PopupSelector).remove()
        await pilot.pause()
        assert chat._query_popup() is None
        chat.text = '/'
        await pilot.pause()
        assert chat.text == '/'


def make_image(directory: Path, name: str = 'photo.png') -> Path:
    path = directory / name
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 16)
    return path


async def test_at_bang_completion_keeps_the_attachment_marker(monkeypatch):
    monkeypatch.setattr(footer_module.FileMatcher, 'matches', fake_matches([('photo.png', 'photo.png', False)]))
    app = InputApp()
    async with app.run_test(size=(40, 100)) as pilot:
        chat = app.query_one(ChatInput)
        await pilot.pause()
        await type_text(pilot, chat, 'look at @!ph')
        await pilot.press('enter')
        await pilot.pause()
        assert chat.text == 'look at @!photo.png '
        assert app.submitted == []


async def test_at_bang_completion_uses_the_stripped_prefix(monkeypatch):
    seen: list[str] = []

    def record(self, prefix):
        seen.append(prefix)
        return [('photo.png', 'photo.png', False)]

    monkeypatch.setattr(footer_module.FileMatcher, 'matches', record)
    app = InputApp()
    async with app.run_test(size=(40, 100)) as pilot:
        chat = app.query_one(ChatInput)
        await pilot.pause()
        await type_text(pilot, chat, '@!ph')
        assert seen[-1] == 'ph'


async def test_submit_attaches_a_supported_image(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    make_image(tmp_path)
    app = InputApp()
    async with app.run_test(size=(40, 100)) as pilot:
        chat = app.query_one(ChatInput)
        await pilot.pause()
        chat.text = 'look @!photo.png'
        await pilot.press('enter')
        await pilot.pause()
        assert app.submitted == ['look']
        assert len(app.attached[0]) == 1
        assert app.attached[0][0].startswith('data:image/png;base64,')
        assert chat.text == ''


async def test_submit_sends_an_image_only_message(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    make_image(tmp_path)
    app = InputApp()
    async with app.run_test(size=(40, 100)) as pilot:
        chat = app.query_one(ChatInput)
        await pilot.pause()
        chat.text = '@!photo.png'
        await pilot.press('enter')
        await pilot.pause()
        assert app.submitted == ['']
        assert len(app.attached[0]) == 1


async def test_submit_keeps_an_unsupported_token_as_text(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'notes.txt').write_text('hi')
    app = InputApp()
    async with app.run_test(size=(40, 100)) as pilot:
        chat = app.query_one(ChatInput)
        await pilot.pause()
        chat.text = 'look @!notes.txt'
        await pilot.press('enter')
        await pilot.pause()
        assert app.submitted == ['look @!notes.txt']
        assert app.attached == [[]]


async def test_attachment_hint_counts_the_resolved_images(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    make_image(tmp_path)
    make_image(tmp_path, 'other.jpeg')
    app = InputApp()
    async with app.run_test(size=(40, 100)) as pilot:
        chat = app.query_one(ChatInput)
        await pilot.pause()
        chat.text = 'see @!photo.png'
        await pilot.pause()
        assert chat.border_subtitle == '📎 1 image'
        chat.text = 'see @!photo.png and @!other.jpeg'
        await pilot.pause()
        assert chat.border_subtitle == '📎 2 images'
        chat.text = 'nothing attached'
        await pilot.pause()
        assert chat.border_subtitle == ''
