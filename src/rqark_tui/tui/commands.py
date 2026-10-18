from collections.abc import Sequence

from rqark_app.sop.types import Sop

COMMANDS: tuple[tuple[str, str], ...] = (
    ('/clear', 'Clear the current conversation'),
    ('/close', 'Close this session'),
    ('/compact', 'Compact the current conversation'),
    ('/new', 'Start a new session'),
    ('/stop', 'Stop the current response'),
    ('/models', 'Switch model'),
    ('/agents', 'Switch agent'),
)

NAME_WIDTH = 9


def slash_entries(prefix: str, sops: Sequence[Sop] = ()) -> list[tuple[str, str]]:
    """Return (label, name) matches for a '/'-prefixed input line; a built-in wins a name clash."""
    if not prefix.startswith('/'):
        return []
    entries = [(f'{name:<{NAME_WIDTH}}{desc}', name) for name, desc in COMMANDS if name.startswith(prefix)]
    taken = {name for name, _ in COMMANDS}
    entries.extend((f'/{sop.slug:<{NAME_WIDTH}}{sop.title}', f'/{sop.slug}') for sop in sops if f'/{sop.slug}' not in taken and f'/{sop.slug}'.startswith(prefix))
    return entries
