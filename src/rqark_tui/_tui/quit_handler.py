"""Quit handling for the TUI app.

VS Code's integrated terminal swallows several control keys (Ctrl+C for
copy, Ctrl+Q for quick-open), so Textual's default Ctrl+Q quit binding is
unreliable there. This mixin provides a single terminal-proof quit key —
Ctrl+D (EOF), which every terminal passes through — plus the existing
Esc-x3 fallback and the Ctrl+C "how to quit" hint.
"""

from textual import events
from textual.binding import Binding, BindingsMap


class QuitHandler:
    """Mixin owning every quit-related binding, action and key handler.

    - ``Ctrl+D`` quits (priority binding; works even while typing).
    - ``Ctrl+Q`` is shadowed with a no-op (VS Code swallows it anyway).
    - ``Esc`` pressed ``ESCAPE_EXIT_COUNT`` times also exits.
    - ``Ctrl+C`` with no selection shows the keys that actually quit.
    """

    #: Number of Esc presses required to exit.
    ESCAPE_EXIT_COUNT = 3

    BINDINGS = [
        # Ctrl+Q quits by default, but VS Code's terminal swallows it
        # (workbench.action.quickOpenView). Keep a single reliable quit key:
        # Ctrl+D (EOF) is passed through by every terminal (Terminal.app,
        # iTerm2, VS Code). Ctrl+Q is shadowed with a no-op so it no longer
        # quits. Priority means Ctrl+D quits even while the chat input is
        # focused (TextArea's Ctrl+D "delete right" is shadowed).
        Binding("ctrl+d", "quit", "Quit", show=False, priority=True),
        Binding("ctrl+q", "noop", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._escape_presses = 0
        # Textual's class-level binding merge only considers DOMNode
        # subclasses, so a plain mixin's BINDINGS are ignored there. Re-apply
        # them per key here, mirroring DOMNode._merge_bindings: later sources
        # replace bindings for the same key.
        merged = self._bindings.copy()
        for key, key_bindings in BindingsMap(self.BINDINGS).key_to_bindings.items():
            merged.key_to_bindings[key] = key_bindings
        self._bindings = merged

    def on_key(self, event: events.Key) -> None:
        """Exit after ``ESCAPE_EXIT_COUNT`` consecutive Esc presses."""
        if event.key == 'escape':
            self._escape_presses += 1
            if self._escape_presses >= self.ESCAPE_EXIT_COUNT:
                self.exit()
        else:
            self._escape_presses = 0

    def action_noop(self) -> None:
        """Do nothing (shadows the default Ctrl+Q -> quit binding)."""

    def action_help_quit(self) -> None:
        """Bound to Ctrl+C: tell the user which keys actually quit."""
        quit_keys = [
            key
            for key, active in self.active_bindings.items()
            if active.binding.action in ("quit", "app.quit")
        ]
        if quit_keys:
            keys = ' or '.join(f'[b]{key}[/b]' for key in sorted(quit_keys))
            self.notify(f'Press {keys} to quit the app', title='Quit?')
