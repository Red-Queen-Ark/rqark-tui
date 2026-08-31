import re
import shutil

import wcwidth


class _C:
    RST = '\033[0m'
    BLD = '\033[1m'
    DIM = '\033[2m'
    ITL = '\033[3m'
    UND = '\033[4m'
    RED = '\033[31m'
    DRED = '\033[38;2;185;28;28m'
    GRN = '\033[32m'
    YLW = '\033[33m'
    BLU = '\033[34m'
    MAG = '\033[35m'
    CYN = '\033[36m'
    WHT = '\033[37m'
    GRY = '\033[90m'
    BG = '\033[48;2;20;20;20m'
    BG_SEL = '\033[48;2;45;45;45m'


# CSI ANSI escape sequences (e.g. SGR colours, cursor movement, bracketed-paste markers).
_ANSI_ESC = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')


def _ansi_tokens(text: str) -> list[tuple[bool, str]]:
    """Split *text* into (is_ansi, segment) tokens."""
    tokens: list[tuple[bool, str]] = []
    pos = 0
    for m in _ANSI_ESC.finditer(text):
        start = m.start()
        if start > pos:
            tokens.append((False, text[pos:start]))
        tokens.append((True, m.group(0)))
        pos = m.end()
    if pos < len(text):
        tokens.append((False, text[pos:]))
    return tokens


def _char_width(ch: str) -> int:
    """Display width of a single character; non-printable/control characters count as 0."""
    w = wcwidth.wcwidth(ch)
    if w is None or w < 0:
        return 0
    return w


def display_width(text: str) -> int:
    """Total display width of *text* in columns, ignoring ANSI escape sequences."""
    total = 0
    for is_ansi, seg in _ansi_tokens(text):
        if not is_ansi:
            total += sum(_char_width(ch) for ch in seg)
    return total


def char_index_at_width(line: str, target_width: int) -> int:
    """Index of the first character in *line* that would exceed *target_width* columns."""
    width = 0
    for i, ch in enumerate(line):
        ch_w = _char_width(ch)
        if width + ch_w > target_width:
            return i
        width += ch_w
    return len(line)


def truncate(text: str, max_len: int = 280) -> str:
    """Truncate *text* to *max_len* display columns, ANSI-safe."""
    if max_len < 1:
        return '…'

    result: list[str] = []
    visible_w = 0

    for is_ansi, seg in _ansi_tokens(text):
        if is_ansi:
            result.append(seg)
            continue

        for ch in seg:
            ch_w = _char_width(ch)
            if visible_w + ch_w > max_len:
                result.append('…')
                result.append('\x1b[0m')
                return ''.join(result)
            result.append(ch)
            visible_w += ch_w

    return ''.join(result)


def paint_bg(text: str, width: int, bg: str = _C.BG) -> str:
    """Fill *text* with *bg* across *width* display columns, ANSI-safe.

    Text already contains SGR resets (from wrapping/inline markdown), so the
    background is re-applied after every reset, then padded with background
    spaces up to *width*.
    """
    body = bg + text.replace('\x1b[0m', '\x1b[0m' + bg)
    return body + ' ' * max(0, width - display_width(text)) + _C.RST


def wrap_bg(text: str, bg: str = _C.BG) -> str:
    """Wrap *text* with *bg*, re-applying after SGR resets.

    Text that already carries a background (e.g. a selection highlight) is
    passed through untouched.
    """
    if '\x1b[48' in text:
        return text
    return bg + text.replace('\x1b[0m', '\x1b[0m' + bg) + _C.RST


def term_width() -> int:
    try:
        return shutil.get_terminal_size().columns
    except Exception:
        return 80


def _parse_sgr_codes(seq: str) -> list[str]:
    """Parse an ANSI SGR sequence (without ESC and 'm') into individual codes."""
    inner = seq[2:-1] if seq.startswith('\x1b[') and seq.endswith('m') else seq
    if not inner:
        return []
    return [c for c in inner.split(';') if c]


def _active_sgr(active: list[str]) -> str:
    """Rebuild an ANSI SGR sequence from active code list."""
    if not active:
        return ''
    return f'\x1b[{";".join(active)}m'


def wrap(text: str, max_width: int) -> list[str]:
    """Wrap *text* into lines of at most *max_width* display columns, preserving ANSI escapes where possible."""
    if max_width < 1:
        return [text]

    lines: list[str] = []
    current: list[str] = []
    visible_w = 0
    active: list[str] = []

    for is_ansi, seg in _ansi_tokens(text):
        if is_ansi:
            current.append(seg)
            if seg.endswith('m'):
                for code in _parse_sgr_codes(seg):
                    if code == '0':
                        active = []
                    else:
                        active.append(code)
            continue

        for ch in seg:
            if ch == '\n':
                current.append('\x1b[0m')
                lines.append(''.join(current))
                current = [_active_sgr(active)]
                visible_w = 0
                continue

            ch_w = _char_width(ch)
            if visible_w + ch_w > max_width:
                lines.append(''.join(current) + ('\x1b[0m' if current else ''))
                current = [_active_sgr(active)]
                visible_w = 0

            current.append(ch)
            visible_w += ch_w

    if current:
        lines.append(''.join(current) + ('\x1b[0m' if active else ''))

    return lines if lines else ['']
