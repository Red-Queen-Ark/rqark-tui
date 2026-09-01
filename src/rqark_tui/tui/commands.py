COMMANDS: list[tuple[str, str]] = [
    ('/help', 'Show available commands'),
    ('/new', 'Start a new conversation'),
    ('/clear', 'Clear the current conversation'),
    ('/stop', 'Stop the current response'),
    ('/models', 'Switch model: /models or /models <index|name>'),
    ('/agents', 'Switch agent: /agents or /agents <name>'),
]


def slash_matches(prefix: str) -> list[str]:
    if not prefix.startswith('/'):
        return []
    return [name for name, _ in COMMANDS if name.startswith(prefix)]
