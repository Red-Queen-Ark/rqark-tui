"""Reusable modal dialogs for the TUI.

The only dialog so far is :class:`YesNoDialog` — a small, generic yes/no
confirmation box. It is pushed with :meth:`App.push_screen` and dismisses
with a plain ``bool``:

- ``True`` when the user confirms (the "Yes"-labelled button or Enter on it);
- ``False`` when the user declines (the "No"-labelled button, or Esc).

Both button labels and the default button are configurable, so the same
dialog covers "Quit?", "Delete session?", "Clear chat?" and so on.
"""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class YesNoDialog(ModalScreen[bool]):
    """Generic yes/no confirmation dialog.

    Dismisses with ``True`` for yes, ``False`` for no (including Esc).
    ``Tab`` / ``Shift+Tab`` move between the buttons, ``Left``/``Right`` hop
    between them directly, and ``Enter`` (or ``Ctrl+E``) activates the
    focused / yes button.

    Example:
        app.push_screen(
            YesNoDialog(
                'Are you sure you want to delete this?',
                title='Delete?',
                yes_label='Delete',
                no_label='Keep',
                default_yes=False,
            ),
            lambda confirmed: app.do_delete() if confirmed else None,
        )
    """

    DEFAULT_CSS = """
    YesNoDialog {
        align: center middle;
    }
    #dialog {
        width: auto;
        max-width: 70%;
        height: auto;
        border: round #4FC1FF;
        background: #1A1A1A;
        padding: 1 2;
    }
    #dialog Label {
        color: #e0e0e0;
        text-align: center;
        padding: 0 2 1 2;
    }
    #buttons {
        height: auto;
        align: center middle;
    }
    #buttons Button {
        margin: 1 2;
        min-width: 10;
    }
    #buttons Button:focus {
        text-style: bold;
        background-tint: #4FC1FF 25%;
        outline-left: solid #4FC1FF;
        outline-right: solid #4FC1FF;
    }
    """

    BINDINGS = [
        # Esc = the "No" button. ModalScreen bindings take precedence over the
        # app's, so this also shields the app's Esc-x3 quit handler.
        Binding('escape', 'no', 'No', show=False),
        # Ctrl+E = the "Yes" button. The app's own Ctrl+E (quit) raises
        # SkipAction while this dialog is open, so the key falls through to
        # here: pressing Ctrl+E again confirms — matching quit muscle memory.
        Binding('ctrl+e', 'yes', 'Yes', show=False),
        # Hop between the two buttons without Tab.
        Binding('left,right', 'focus_other', show=False),
    ]

    def __init__(self, message: str, *, title: str = 'Confirm', yes_label: str = 'Yes', no_label: str = 'No', default_yes: bool = True) -> None:
        """Create a yes/no dialog.

        Args:
            message: The question to show.
            title: Dialog border title.
            yes_label: Text of the confirming button.
            no_label: Text of the declining button.
            default_yes: Whether the yes button starts focused (Enter confirms).
        """
        super().__init__()
        self._message = message
        self._title = title
        self._yes_label = yes_label
        self._no_label = no_label
        self._default_yes = default_yes

    def compose(self) -> ComposeResult:
        with Vertical(id='dialog'):
            yield Label(self._message)
            with Horizontal(id='buttons'):
                # Yes on the left, No on the right (reading order).
                yield Button(self._yes_label, id='yes', variant='primary', compact=True)
                yield Button(self._no_label, id='no', variant='default', compact=True)

    def on_mount(self) -> None:
        # The border lives on the #dialog container, so the title/subtitle go
        # there too (a Screen-level border_title is invisible without a
        # screen border).
        dialog = self.query_one('#dialog')
        dialog.border_title = self._title
        dialog.border_subtitle = 'Enter to choose · Tab to switch · Esc to cancel'
        default_button = '#yes' if self._default_yes else '#no'
        self.query_one(default_button, Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Any button click dismisses with the answer."""
        self.dismiss(event.button.id == 'yes')

    def action_yes(self) -> None:
        """Ctrl+E: confirm, same as the "Yes" button."""
        self.dismiss(True)

    def action_no(self) -> None:
        """Esc: decline, same as the "No" button."""
        self.dismiss(False)

    def action_focus_other(self) -> None:
        """Left/Right: move focus to the other button."""
        yes = self.query_one('#yes', Button)
        no = self.query_one('#no', Button)
        (no if self.focused is yes else yes).focus()
