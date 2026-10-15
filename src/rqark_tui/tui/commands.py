COMMANDS: tuple[tuple[str, str], ...] = (
    ('/clear', 'Clear the current conversation'),
    ('/close', 'Close this session'),
    ('/compact', 'Compact the current conversation'),
    ('/new', 'Start a new session'),
    ('/stop', 'Stop the current response'),
    ('/models', 'Switch model'),
    ('/agents', 'Switch agent'),
)


def slash_entries(prefix: str) -> list[tuple[str, str]]:
    """Return (label, name) matches for a '/'-prefixed input line."""
    if not prefix.startswith('/'):
        return []
    return [(f'{name:<9}{desc}', name) for name, desc in COMMANDS if name.startswith(prefix)]
