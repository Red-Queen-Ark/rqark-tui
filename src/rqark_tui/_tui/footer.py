import ctypes
import sys
from typing import Callable

from textual import events
from textual.message import Message
from textual.widgets import TextArea

# --- macOS physical modifier-state detection ---------------------------------
# Same trick as `libs/tui/input.py` on Windows (GetAsyncKeyState), but for macOS:
# query the current hardware key state via CoreGraphics, so Shift+Enter / Ctrl+Enter
# work even in terminals that send the same byte as plain Enter (e.g. Terminal.app).

_CG_EVENT_SOURCE_COMBINED_SESSION_STATE = 1
_VK_LEFT_SHIFT = 56
_VK_RIGHT_SHIFT = 60
_VK_LEFT_CONTROL = 59
_VK_RIGHT_CONTROL = 62

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
        border: round #4FC1FF;
        padding: 1 2;
        background: #1e1e1e;
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
        self._update_height()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Grow/shrink the input height as the number of lines changes."""
        self._update_height()

    def _update_height(self) -> None:
        """Set the widget height to fit the content: 1 line by default, growing up to MAX_LINES.

        The box model is border-box, so the total height also includes the
        2 border rows and 2 padding rows.
        """
        lines = min(max(self.document.line_count, 1), self.MAX_LINES)
        self.styles.height = lines + 4

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
        self.post_message(self.Submitted(self, text))
        self.clear()
