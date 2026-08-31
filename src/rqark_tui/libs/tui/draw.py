import atexit
import shutil
import subprocess
import sys
from typing import Literal

DEFAULT_TERM_HEIGHT = 24
DEFAULT_TERM_WIDTH = 80

from rqark_tui.libs.tui.ansi import _C, wrap_bg


class TerminalDraw:
    def __init__(self):
        self._enable_windows_ansi()
        sys.stdout.write('\x1b[?2004h')
        sys.stdout.flush()
        atexit.register(self._disable_bracketed_paste)
        self.width = DEFAULT_TERM_WIDTH
        self.height = DEFAULT_TERM_HEIGHT
        self._buf: list[str] = []
        self.resize()

    @staticmethod
    def _enable_windows_ansi() -> None:
        if sys.platform == 'win32':
            subprocess.run('', shell=True)

    @staticmethod
    def _disable_bracketed_paste() -> None:
        sys.stdout.write('\x1b[?2004l')
        sys.stdout.flush()

    def restore(self) -> None:
        """Fully restore the terminal: show cursor, reset styles, clear screen,
        disable bracketed paste. Call before leaving the TUI."""
        sys.stdout.write('\033[?25h\033[0m\033[2J\033[H\x1b[?2004l')
        sys.stdout.flush()

    def clear(self):
        fill = _C.BG + ' ' * (self.width * self.height) + _C.RST
        self._buf = ['\033[?25l', '\033[2J', '\033[H', fill]

    def gotoxy(self, row: int, col: int):
        self._buf.append(f'\033[{row + 1};{col + 1}H')

    def resize(self):
        try:
            size = shutil.get_terminal_size()
            self.width = size.columns
            self.height = size.lines
        except Exception as e:
            sys.stderr.write(f'[DRAW:RESIZE] {e}\n')
            sys.stderr.flush()
        return self.width, self.height

    def update(self):
        self.resize()
        sys.stdout.write(''.join(self._buf))
        sys.stdout.flush()
        self._buf = []

    def show_cursor(self):
        self._buf.append('\033[?25h')

    def hide_cursor(self):
        self._buf.append('\033[?25l')

    def draw_char(self, row: int, col: int, char: str):
        if 0 <= row < self.height and 0 <= col < self.width:
            self.gotoxy(row, col)
            self._buf.append(wrap_bg(char))

    def draw_line(self, row: int, col: int, length: int, direction: Literal['horizontal', 'vertical'] = 'horizontal', char: str = '─', color: str = ''):
        if direction == 'horizontal':
            if 0 <= row < self.height and col < self.width:
                start = max(0, col)
                end = min(self.width, col + length)
                if end > start:
                    self.gotoxy(row, start)
                    seg = char * (end - start)
                    seg = (color + seg + _C.RST) if color else seg
                    self._buf.append(wrap_bg(seg))
        elif direction == 'vertical':
            for i in range(length):
                self.draw_char(row + i, col, char)
        else:
            raise ValueError("direction must be 'horizontal' or 'vertical'")
