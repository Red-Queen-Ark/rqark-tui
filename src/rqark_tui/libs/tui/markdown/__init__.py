import re

HR_MAX_WIDTH = 72
from rqark_tui.libs.tui.ansi import _C, term_width

from .highlight import highlight as _hl
from .markdown_table import TableRenderer

_MD_BOLD_ITALIC = re.compile(r'\*\*\*(.+?)\*\*\*')
_MD_BOLD = re.compile(r'\*\*(.+?)\*\*')
_MD_ITALIC = re.compile(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)')
_MD_INLINE_CODE = re.compile(r'`([^`]+)`')
_MD_HR = re.compile(r'^[-*_]{3,}\s*$')
_MD_H = re.compile(r'^(#{1,6})\s+(.+)$')
_MD_UL = re.compile(r'^(\s*)[-*+]\s+(.+)$')
_MD_OL = re.compile(r'^(\s*)\d+\.\s+(.+)$')
_MD_BQ = re.compile(r'^>\s?(.+)$')
_MD_LINK = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
_MD_CODE_FENCE = re.compile(r'^```(\w*)$')
_MD_TABLE_ROW = re.compile(r'^\|(.+)\|\s*$')
_MD_TABLE_SEP = re.compile(r'^\|(\s*:?-+:?\s*\|)+\s*$')


class MarkdownRenderer:
    def __init__(self) -> None:
        self._buf = ''
        self._in_fence = False
        self._fence_lang = ''
        self._fence_lines: list[str] = []
        self._table = TableRenderer()

    def feed(self, text: str) -> str:
        self._buf += text
        out: list[str] = []

        while '\n' in self._buf:
            line, self._buf = self._buf.split('\n', 1)
            rendered = self._render_line(line)
            if rendered is not None:
                out.append(rendered)

        return '\n'.join(out) + ('\n' if out else '')

    def flush(self) -> str:
        out: list[str] = []
        if self._buf:
            rendered = self._render_line(self._buf)
            if rendered is not None:
                out.append(rendered)
            self._buf = ''

        flushed = self._table.flush(self._inline)
        if flushed:
            out.append(flushed)

        if self._in_fence:
            code = '\n'.join(self._fence_lines)
            self._in_fence = False
            lang = self._fence_lang
            self._fence_lines = []
            self._fence_lang = ''
            out.append(self._highlight_code(code, lang))
        return '\n'.join(out)

    def _render_line(self, raw: str) -> str | None:
        m = _MD_CODE_FENCE.match(raw)
        if m:
            flushed = self._table.flush(self._inline)
            prefix = (flushed + '\n') if flushed else ''
            if self._in_fence:
                code = '\n'.join(self._fence_lines)
                self._in_fence = False
                self._fence_lines = []
                lang = self._fence_lang
                self._fence_lang = ''
                highlighted = self._highlight_code(code, lang)
                return prefix + highlighted
            else:
                self._in_fence = True
                self._fence_lang = m.group(1)
                self._fence_lines = []
                lang_label = f' {self._fence_lang}' if self._fence_lang else ''
                return prefix + f'{_C.GRY}┌─ code{lang_label}{_C.RST}'

        if self._in_fence:
            self._fence_lines.append(raw)
            return None

        tm = _MD_TABLE_ROW.match(raw)
        is_sep = bool(tm and _MD_TABLE_SEP.match(raw))

        if self._table.is_active():
            if tm and not is_sep:
                cells = [c.strip() for c in tm.group(1).split('|')]
                self._table.feed_row(cells)
                return None
            else:
                table_out = self._table.flush(self._inline)
                rendered = self._render_block(raw)
                if rendered is not None:
                    return (table_out + '\n' + rendered) if table_out else rendered
                return table_out if table_out else None

        if self._table.has_pending_header():
            if is_sep:
                sep_cells = [c.strip() for c in tm.group(1).split('|')]
                self._table.feed_sep(sep_cells)
                return None
            else:
                flushed = self._table.flush_pending_header(self._inline)
                rendered = self._render_block(raw)
                if rendered is not None:
                    return flushed + '\n' + rendered
                return flushed

        if tm and not is_sep:
            self._table.feed_header([c.strip() for c in tm.group(1).split('|')])
            return None

        return self._render_block(raw)

    def _render_block(self, raw: str) -> str | None:
        if not raw.strip():
            return ''

        if _MD_HR.match(raw):
            w = min(term_width(), HR_MAX_WIDTH)
            return f'{_C.GRY}{"─" * w}{_C.RST}'

        hm = _MD_H.match(raw)
        if hm:
            level = len(hm.group(1))
            text = self._inline(hm.group(2))
            if level == 1:
                return f'{_C.BLD}{_C.UND}{_C.WHT}{text}{_C.RST}'
            elif level == 2:
                return f'{_C.BLD}{_C.WHT}{text}{_C.RST}'
            else:
                return f'{_C.BLD}{text}{_C.RST}'

        um = _MD_UL.match(raw)
        if um:
            indent = um.group(1)
            text = self._inline(um.group(2))
            return f'{indent}{_C.GRY}•{_C.RST} {text}'

        om = _MD_OL.match(raw)
        if om:
            indent = om.group(1)
            text = self._inline(om.group(2))
            num = raw.strip().split('.')[0]
            return f'{indent}{_C.GRY}{num}.{_C.RST} {text}'

        bm = _MD_BQ.match(raw)
        if bm:
            text = self._inline(bm.group(1))
            return f'{_C.GRY}▎{_C.RST} {text}'

        return self._inline(raw)

    @staticmethod
    def _highlight_code(code: str, lang: str) -> str:
        if not code.strip():
            return ''
        try:
            highlighted = _hl(code, lang)
        except Exception:
            return '\n'.join(f'{_C.GRY}  {line}{_C.RST}' for line in code.split('\n'))
        lines = highlighted.split('\n')
        return '\n'.join(f'{_C.GRY}  {_C.RST}{line}' for line in lines)

    def _inline(self, text: str) -> str:
        text = _MD_BOLD_ITALIC.sub(lambda m: f'{_C.BLD}{_C.ITL}{m.group(1)}{_C.RST}', text)
        text = _MD_BOLD.sub(lambda m: f'{_C.BLD}{m.group(1)}{_C.RST}', text)
        text = _MD_ITALIC.sub(lambda m: f'{_C.ITL}{m.group(1)}{_C.RST}', text)
        text = _MD_INLINE_CODE.sub(lambda m: f'{_C.CYN}{m.group(1)}{_C.RST}', text)
        text = _MD_LINK.sub(lambda m: f'{m.group(1)} {_C.GRY}({m.group(2)}){_C.RST}', text)
        return text
