import ctypes
import sys
from typing import Callable

from rich.markup import escape
from textual import events
from textual.message import Message
from textual.widgets import TextArea

from rqark_tui.tui.commands import slash_entries
from rqark_tui.tui.components.file_match import FileMatcher
from rqark_tui.tui.components.main import MessagePane
from rqark_tui.tui.components.popup import Entry, PopupSelector

# --- macOS physical modifier-state detection ---------------------------------
# Same trick as `libs/tui/input.py` on Windows (GetAsyncKeyState), but for macOS:
# query the current hardware key state via CoreGraphics, so Shift+Enter / Ctrl+Enter
# work even in terminals that send the same byte as plain Enter (e.g. Terminal.app).

_CG_EVENT_SOURCE_COMBINED_SESSION_STATE = 1
_VK_LEFT_SHIFT = 56
_VK_RIGHT_SHIFT = 60
_VK_LEFT_CONTROL = 59
_VK_RIGHT_CONTROL = 62
_VK_RETURN = 36
_VK_KEYPAD_ENTER = 76

_cg_event_source_key_state: Callable[..., bool] | None = None

if sys.platform == 'darwin':
    try:
        _app_services = ctypes.CDLL('/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices')
        _cg_event_source_key_state = _app_services.CGEventSourceKeyState
        _cg_event_source_key_state.restype = ctypes.c_bool
        _cg_event_source_key_state.argtypes = [ctypes.c_uint32, ctypes.c_ushort]
    except OSError:
        _cg_event_source_key_state = None


def _physical_key_down(keycode: int) -> bool:
    """Return True if the physical key with the given macOS keycode is held down."""
    if _cg_event_source_key_state is None:
        return False
    try:
        return bool(_cg_event_source_key_state(_CG_EVENT_SOURCE_COMBINED_SESSION_STATE, keycode))
    except Exception:
        return False


def _is_shift_pressed() -> bool:
    """Return True if Shift is physically held (macOS only; False elsewhere)."""
    return _physical_key_down(_VK_LEFT_SHIFT) or _physical_key_down(_VK_RIGHT_SHIFT)


def _is_ctrl_pressed() -> bool:
    """Return True if Control is physically held (macOS only; False elsewhere)."""
    return _physical_key_down(_VK_LEFT_CONTROL) or _physical_key_down(_VK_RIGHT_CONTROL)


def _is_return_pressed() -> bool:
    """Return True if Return/Enter is physically held (macOS only; False elsewhere)."""
    return _physical_key_down(_VK_RETURN) or _physical_key_down(_VK_KEYPAD_ENTER)


class ChatInput(TextArea):
    """Multi-line input box that grows from 1 up to 10 lines.

    - `Enter` submits the current text (posts a `ChatInput.Submitted` message).
    - `Shift+Enter` / `Ctrl+Enter` / `Ctrl+J` inserts a newline.
    """

    class Submitted(Message):
        """Posted when the user presses Enter to submit the current text."""

        def __init__(self, chat_input: 'ChatInput', text: str) -> None:
            super().__init__()
            self.chat_input = chat_input
            self.text = text

        @property
        def control(self) -> 'ChatInput':
            """Alias for self.chat_input."""
            return self.chat_input

    DEFAULT_CSS = """
    ChatInput {
        border: round #303030;
        margin: 0 0;
        padding: 0 2;
        background: transparent;
        color: #e0e0e0;
    }
    ChatInput:focus {
        border: round #4FC1FF;
    }
    """

    #: Maximum number of content lines the input may grow to.
    MAX_LINES = 10

    def __init__(self, placeholder: str = 'Type a message… (Enter to send, Shift+Enter for newline)') -> None:
        super().__init__(soft_wrap=True, show_line_numbers=False, tab_behavior='indent')
        self.placeholder = placeholder
        self._matcher = FileMatcher()
        self._popup: PopupSelector | None = None
        self._message_pane: MessagePane | None = None
        self._pick_done: Callable[[Entry | None], None] | None = None
        self._update_height()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Grow/shrink the input height as the number of lines changes."""
        self._update_height()
        self._update_completion()

    def _update_height(self) -> None:
        """Set the widget height to fit the content: 1 line by default, growing up to MAX_LINES.

        The box model is border-box, so the total height also includes the
        2 border rows. Vertical padding is 0 (kept in sync with the CSS), so
        the single-line input is as slim as the HeaderBar (height 3).
        """
        lines = min(max(self.document.line_count, 1), self.MAX_LINES)
        self.styles.height = lines + 2

    @property
    def popup_active(self) -> bool:
        """True while the popup demands keys (picker or completion), not a passive plan view."""
        popup = self._query_popup()
        return popup is not None and popup.display and popup.selectable

    def _query_popup(self) -> PopupSelector | None:
        if self._popup is None:
            try:
                self._popup = self.app.query_one(PopupSelector)
            except Exception:
                return None
        return self._popup

    def _query_message_pane(self) -> MessagePane | None:
        if self._message_pane is None:
            try:
                self._message_pane = self.app.query_one(MessagePane)
            except Exception:
                return None
        return self._message_pane

    def begin_pick(self, entries: list[Entry], *, title: str = '', index: int = 0, on_done: Callable[[Entry | None], None]) -> None:
        """Open the popup in picker mode; keys resolve ``on_done`` with the chosen entry or None."""
        popup = self._query_popup()
        if popup is None or not entries:
            on_done(None)
            return
        self._pick_done = on_done
        popup.show(entries, title=title, index=index)
        self.focus()

    def _finish_pick(self, entry: Entry | None) -> None:
        popup = self._query_popup()
        if popup is not None:
            popup.hide()
        on_done, self._pick_done = self._pick_done, None
        self.clear()
        if on_done is not None:
            on_done(entry)

    def _file_prefix(self) -> tuple[str, int | None]:
        before = self.document.get_text_range((0, 0), self.cursor_location)
        at_index = before.rfind('@')
        if at_index < 0:
            return '', None
        if at_index > 0 and before[at_index - 1] not in ' \t\n':
            return '', None
        rest = before[at_index + 1:]
        if any(char.isspace() for char in rest):
            return '', None
        return rest, at_index

    def _update_completion(self) -> None:
        popup = self._query_popup()
        if popup is None:
            return
        if self._pick_done is not None:
            return
        if self.document.line_count == 1 and self.text.startswith('/'):
            popup.show(slash_entries(self.text))
            return
        prefix, at_index = self._file_prefix()
        if at_index is not None:
            popup.show([(escape(display), value) for display, value, _ in self._matcher.matches(prefix)])
            return
        if popup.display and popup.selectable:
            popup.hide()

    def _select_completion(self) -> None:
        popup = self._query_popup()
        if popup is None or not popup.display:
            return
        entry = popup.selected_entry
        if entry is None:
            popup.hide()
            return
        _display, value = entry
        if self.document.line_count == 1 and self.text.startswith('/'):
            popup.hide()
            self.text = value
            self.submit()
            return
        prefix, at_index = self._file_prefix()
        if at_index is None:
            popup.hide()
            return
        head = self.document.get_text_range((0, 0), self.cursor_location)[:at_index]
        row = head.count('\n')
        col = len(head) - (head.rfind('\n') + 1)
        self.replace(f'@{value} ', (row, col), self.cursor_location)
        popup.hide()

    def _note_escape(self) -> None:
        """Keep Esc meaningful in the input: it must not be swallowed by TextArea.

        ``TextArea`` moves focus to the next widget on Esc when ``tab_behavior`` is
        ``indent``, which would silently drop the key before the app's Esc-x3 quit
        handler sees it. Consuming it here keeps the caret in the input and lets the
        quit counter still see the press.
        """
        from rqark_tui.tui.components.quit_handler import QuitHandler

        if isinstance(self.app, QuitHandler):
            self.app.note_escape()

    async def _on_key(self, event: events.Key) -> None:
        """Intercept Enter to submit, and let Shift/Ctrl+Enter insert newlines.

        Enter handling has three layers so it works on every terminal:

        1. The terminal reports the modifiers itself (CSI-u / kitty keyboard
           protocol; iTerm2, kitty, WezTerm, …) — the key arrives as
           ``shift+enter`` / ``ctrl+enter``.
        2. The terminal does *not* report modifiers (macOS Terminal.app sends
           the same byte as Enter) — we check the physical key state directly
           via CoreGraphics (same idea as ``GetAsyncKeyState`` on Windows).
        3. ``Ctrl+J`` sends a line feed byte (0x0A), which every terminal
           reports distinctly from Enter (0x0D).
        """
        if event.key == 'ctrl+c' and self.selection.is_empty:
            pane = self._query_message_pane()
            if pane is not None and pane.copy_selection():
                event.stop()
                event.prevent_default()
                return
        if event.key == 'circumflex_accent' and _is_return_pressed():
            # Terminals that send ESC+CR / ESC+LF for a *modified* Enter (e.g.
            # "Use Option as Meta", or a custom Shift+Enter binding) make Textual
            # reissue the ESC byte as a phantom '^' key when the key auto-repeats,
            # right before the real Enter/LF event. The physical Return key is
            # held down during that repeat, but NOT when the user genuinely types
            # '^' (Shift+6) — so this reliably distinguishes the two. Drop the
            # phantom; the Enter/LF event that follows decides newline vs submit.
            event.stop()
            event.prevent_default()
            return
        popup = self._query_popup()
        if popup is not None and popup.display:
            if self._pick_done is not None:
                if event.key in ('up', 'down', 'tab'):
                    event.stop()
                    event.prevent_default()
                    popup.move(1 if event.key != 'up' else -1)
                    return
                if event.key in ('enter', 'escape'):
                    event.stop()
                    event.prevent_default()
                    self._finish_pick(popup.selected_entry if event.key == 'enter' else None)
                    return
            elif popup.selectable:
                if event.key in ('up', 'down', 'tab'):
                    event.stop()
                    event.prevent_default()
                    popup.move(1 if event.key != 'up' else -1)
                    return
                if event.key == 'escape':
                    event.stop()
                    event.prevent_default()
                    popup.hide()
                    return
                if event.key == 'enter':
                    event.stop()
                    event.prevent_default()
                    self._select_completion()
                    return
            elif event.key == 'escape':
                event.stop()
                event.prevent_default()
                popup.hide()
                return
        if event.key == 'escape':
            event.stop()
            event.prevent_default()
            self._note_escape()
            return
        if event.key == 'enter':
            event.stop()
            event.prevent_default()
            if _is_shift_pressed() or _is_ctrl_pressed():
                self.insert('\n')
            else:
                self.submit()
            return
        if event.key in ('shift+enter', 'ctrl+enter', 'ctrl+shift+enter', 'shift+ctrl+enter', 'ctrl+j', 'newline'):
            event.stop()
            event.prevent_default()
            self.insert('\n')
            return
        await super()._on_key(event)

    def submit(self) -> None:
        """Send the current content and clear the input box."""
        text = self.text.strip('\n')
        if not text:
            return
        popup = self._query_popup()
        if popup is not None:
            popup.hide()
        self.post_message(self.Submitted(self, text))
        self.clear()
