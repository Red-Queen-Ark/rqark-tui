import re
from collections.abc import Callable

from libs.ansi import _C, display_width, term_width, wrap

_MD_STRIP_BOLD = re.compile(r'\*\*(.+?)\*\*')
_MD_STRIP_ITALIC = re.compile(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)')
_MD_STRIP_CODE = re.compile(r'`([^`]+)`')
_MD_STRIP_LINK = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')


def _strip_md(text: str) -> str:
    text = _MD_STRIP_BOLD.sub(r'\1', text)
    text = _MD_STRIP_ITALIC.sub(r'\1', text)
    text = _MD_STRIP_CODE.sub(r'\1', text)
    text = _MD_STRIP_LINK.sub(r'\1 (\2)', text)
    return text


def _parse_align(sep: str) -> str:
    sep = sep.strip()
    if sep.startswith(':') and sep.endswith(':'):
        return 'center'
    elif sep.endswith(':'):
        return 'right'
    else:
        return 'left'


class TableRenderer:
    def __init__(self) -> None:
        self._table_rows: list[list[str]] = []
        self._table_align: list[str] = []
        self._pending_header: list[str] | None = None
        self._in_table = False

    def feed_header(self, cells: list[str]) -> None:
        self._pending_header = cells

    def feed_sep(self, cells: list[str]) -> None:
        self._in_table = True
        self._table_rows = [self._pending_header or []]
        self._table_align = [_parse_align(c) for c in cells]
        self._pending_header = None

    def feed_row(self, cells: list[str]) -> None:
        self._table_rows.append(cells)

    def is_active(self) -> bool:
        return self._in_table

    def has_pending_header(self) -> bool:
        return self._pending_header is not None

    def flush_pending_header(self, inline_fn: Callable[[str], str]) -> str:
        if self._pending_header is not None:
            header_text = ' | '.join(self._pending_header)
            self._pending_header = None
            return inline_fn(header_text)
        return ''

    def flush(self, inline_fn: Callable[[str], str]) -> str:
        parts: list[str] = []
        pending = self.flush_pending_header(inline_fn)
        if pending:
            parts.append(pending)
        if self._in_table:
            table_out = self._render_table(inline_fn)
            if table_out:
                parts.append(table_out)
            self._in_table = False
            self._table_rows = []
            self._table_align = []
        return '\n'.join(parts)

    def _column_widths(self, ncols: int, rows: list[list[str]]) -> list[int]:
        col_widths = [3] * ncols
        for row in rows:
            for i in range(min(len(row), ncols)):
                visible = _strip_md(row[i])
                col_widths[i] = max(col_widths[i], display_width(visible))

        # ChatBuffer re-wraps every line at term_width() - 2, so the table must
        # fit inside that budget or the borders get split onto the next line.
        term_w = term_width() - 2
        overhead = 3 * ncols + 1
        available = term_w - overhead
        if available < ncols * 3:
            col_widths = [max(3, available // ncols) for _ in range(ncols)]
        else:
            total = sum(col_widths)
            if total > available:
                scale = available / total
                col_widths = [max(3, int(w * scale)) for w in col_widths]
                while sum(col_widths) > available:
                    widest = max(range(ncols), key=lambda i: col_widths[i])
                    if col_widths[widest] <= 3:
                        break
                    col_widths[widest] -= 1
            leftover = available - sum(col_widths)
            for i in range(leftover):
                col_widths[i % ncols] += 1
        return col_widths

    def _render_table(self, inline_fn: Callable[[str], str]) -> str:
        if not self._table_rows:
            return ''

        ncols = max(len(row) for row in self._table_rows)
        while len(self._table_align) < ncols:
            self._table_align.append('left')

        col_widths = self._column_widths(ncols, self._table_rows)

        def _pad_line(line: str, width: int, align: str) -> str:
            line_w = display_width(line)
            padding = max(0, width - line_w)
            if align == 'right':
                return ' ' * padding + line + _C.RST
            elif align == 'center':
                left = padding // 2
                return ' ' * left + line + ' ' * (padding - left) + _C.RST
            else:
                return line + ' ' * padding + _C.RST

        def _wrap_cell(cell: str, width: int) -> list[str]:
            wrapped = wrap(cell, width)
            return wrapped if wrapped else ['']

        lines: list[str] = []
        c = _C

        parts = ['─' * (w + 2) for w in col_widths]
        lines.append(f'{c.GRY}┌{"┬".join(parts)}┐{c.RST}')

        for ri, row in enumerate(self._table_rows):
            cell_lines: list[list[str]] = []
            max_h = 1
            for i in range(ncols):
                raw_cell = row[i] if i < len(row) else ''
                styled = inline_fn(raw_cell)
                wrapped = _wrap_cell(styled, col_widths[i])
                cell_lines.append([_pad_line(ln, col_widths[i], self._table_align[i]) for ln in wrapped])
                max_h = max(max_h, len(wrapped))

            for li in range(max_h):
                cells: list[str] = []
                for i in range(ncols):
                    content = cell_lines[i][li] if li < len(cell_lines[i]) else ' ' * col_widths[i]
                    cells.append(' ' + content + ' ')
                lines.append(f'{c.GRY}│{c.RST}' + f'{c.GRY}│{c.RST}'.join(cells) + f'{c.GRY}│{c.RST}')

            if ri == 0:
                parts = ['─' * (w + 2) for w in col_widths]
                lines.append(f'{c.GRY}├{"┼".join(parts)}┤{c.RST}')

        parts = ['─' * (w + 2) for w in col_widths]
        lines.append(f'{c.GRY}└{"┴".join(parts)}┘{c.RST}')

        return '\n'.join(lines)
