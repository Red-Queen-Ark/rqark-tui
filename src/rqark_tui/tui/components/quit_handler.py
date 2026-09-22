"""Quit handling for the TUI app.

The user's terminal swallows several control keys (Ctrl+D, Ctrl+Q), so
Ctrl+E (readline end-of-line) is the quit key, with an Esc-x3 fallback.
Quitting goes through a yes/no confirmation dialog first.
"""

from typing import TYPE_CHECKING

from textual import events
from textual.actions import SkipAction
from textual.binding import Binding, BindingsMap

from rqark_tui.tui.components.dialog import YesNoDialog

if TYPE_CHECKING:
    from textual.app import App

    _AppBase = App
else:
    _AppBase = object


class QuitHandler(_AppBase):
    """Mixin owning every quit-related binding, action and key handler.

    - ``Ctrl+E`` asks for confirmation (priority binding; works even while typing).
    - ``Esc`` pressed ``ESCAPE_EXIT_COUNT`` times also asks for confirmation.
    """

    #: Number of Esc presses required to ask for confirmation.
    ESCAPE_EXIT_COUNT = 3

    BINDINGS = [
        # Ctrl+E (readline end-of-line) passes through the user's terminal,
        # unlike Ctrl+D and Ctrl+Q. Priority means it quits even while the
        # chat input is focused (TextArea binds ctrl+e to "end of line").
        Binding('ctrl+e', 'quit', 'Quit', show=False, priority=True)
    ]

    def __init__(self) -> None:
        super().__init__()
        self._escape_presses = 0
        # True while a confirmation dialog push is scheduled but not yet shown.
        self._quit_pending = False
        # Textual's class-level binding merge only considers DOMNode
        # subclasses, so a plain mixin's BINDINGS are ignored there. Re-apply
        # them per key here, mirroring DOMNode._merge_bindings: later sources
        # replace bindings for the same key. The mixin's own BINDINGS class
        # attribute is named explicitly — ``self.BINDINGS`` would resolve to a
        # subclass's list and silently drop the quit key.
        merged = self._bindings.copy()
        for key, key_bindings in BindingsMap(QuitHandler.BINDINGS).key_to_bindings.items():
            merged.key_to_bindings[key] = key_bindings
        for key in ('ctrl+q', 'ctrl+c'):
            merged.key_to_bindings.pop(key, None)
        self._bindings = merged

    @property
    def _quit_dialog_open(self) -> bool:
        """True while the quit confirmation dialog is on screen."""
        return isinstance(self.screen, YesNoDialog)

    def on_key(self, event: events.Key) -> None:
        """Ask for confirmation after ``ESCAPE_EXIT_COUNT`` consecutive Esc presses.

        While the confirmation dialog is open, it owns the Esc key (its
        binding is checked after this handler, and dismisses the dialog), so
        the counter is reset instead of fed.
        """
        if event.key != 'escape' or self._quit_dialog_open:
            self._escape_presses = 0
            return
        self.note_escape()

    def note_escape(self) -> None:
        """Count one Esc press, wherever it was handled (see ``ChatInput``)."""
        if self._quit_dialog_open:
            self._escape_presses = 0
            return
        self._escape_presses += 1
        if self._escape_presses >= self.ESCAPE_EXIT_COUNT:
            self._escape_presses = 0
            self.call_later(self.action_quit)

    async def action_quit(self) -> None:
        """Ctrl+E / Esc-x3: confirm before actually quitting."""
        if self._quit_dialog_open:
            # Let the dialog's own Ctrl+E binding handle the key: pressing
            # Ctrl+E again while the dialog is open confirms the quit.
            raise SkipAction
        if self._quit_pending:
            return  # A push is already scheduled — don't schedule another.
        self._quit_pending = True
        # Defer the push until the current key event has fully dispatched.
        # Otherwise the very Esc that triggered the dialog would then be
        # consumed by the dialog's own Esc binding, dismissing it before it
        # mounts.
        self.call_later(self._push_quit_dialog)

    def _push_quit_dialog(self) -> None:
        self._quit_pending = False
        if self._quit_dialog_open:
            return
        self.push_screen(YesNoDialog('Are you sure you want to quit?', title='Quit?', yes_label='Quit', no_label='Cancel'), self._on_quit_confirmed)

    def _on_quit_confirmed(self, confirmed: bool | None) -> None:
        """Dismissal callback: only exit on an explicit yes."""
        if confirmed:
            self.exit()
