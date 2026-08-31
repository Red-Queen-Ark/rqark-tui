import sys
from typing import Any

try:
    import termios
    import tty

    _WINDOWS = False
except ImportError:
    import ctypes
    import msvcrt

    _WINDOWS = True


_WIN_ESCAPE_MAP: dict[str, str] = {'H': '\x1b[A', 'P': '\x1b[B', 'M': '\x1b[C', 'K': '\x1b[D'}

_PASTE_MARKERS = {'\x1b[200~', '\x1b[201~'}

_VK_SHIFT = 0x10
_VK_CONTROL = 0x11
_STD_OUTPUT_HANDLE = -11
_STD_INPUT_HANDLE = -10
_ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
_ENABLE_PROCESSED_INPUT = 0x0001

_win_orig_input_mode: int | None = None


def enable_windows_ansi() -> None:
    if not _WINDOWS:
        return
    kernel32 = ctypes.windll.kernel32
    kernel32.GetStdHandle.restype = ctypes.c_void_p
    kernel32.GetStdHandle.argtypes = [ctypes.c_uint32]
    kernel32.GetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    kernel32.SetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.c_uint32]

    out_handle = kernel32.GetStdHandle(_STD_OUTPUT_HANDLE)
    out_mode = ctypes.c_uint32()
    if kernel32.GetConsoleMode(out_handle, ctypes.byref(out_mode)):
        kernel32.SetConsoleMode(out_handle, out_mode.value | _ENABLE_VIRTUAL_TERMINAL_PROCESSING)

    in_handle = kernel32.GetStdHandle(_STD_INPUT_HANDLE)
    in_mode = ctypes.c_uint32()
    if kernel32.GetConsoleMode(in_handle, ctypes.byref(in_mode)):
        global _win_orig_input_mode
        _win_orig_input_mode = in_mode.value
        kernel32.SetConsoleMode(in_handle, in_mode.value & ~_ENABLE_PROCESSED_INPUT)


def _win_key_down(vk: int) -> bool:
    user32 = ctypes.windll.user32
    user32.GetAsyncKeyState.restype = ctypes.c_short
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    return user32.GetAsyncKeyState(vk) < 0


def save_terminal_state() -> Any:
    if _WINDOWS:
        return None
    return termios.tcgetattr(sys.stdin.fileno())


def restore_terminal_state(state: Any) -> None:
    if _WINDOWS:
        global _win_orig_input_mode
        if _win_orig_input_mode is not None:
            kernel32 = ctypes.windll.kernel32
            kernel32.GetStdHandle.restype = ctypes.c_void_p
            kernel32.GetStdHandle.argtypes = [ctypes.c_uint32]
            kernel32.SetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            in_handle = kernel32.GetStdHandle(_STD_INPUT_HANDLE)
            kernel32.SetConsoleMode(in_handle, _win_orig_input_mode)
            _win_orig_input_mode = None
        return
    if state is None:
        return
    termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, state)


def _read_escape() -> str:
    seq = sys.stdin.read(1)
    if seq == '[':
        while True:
            c = sys.stdin.read(1)
            seq += c
            if c == '~' or c.isalpha():
                break
    elif seq == 'O':
        seq += sys.stdin.read(1)
    return seq


def _get_input_getch_windows() -> None | str:
    ch = msvcrt.getwch()
    if ch in ('\x00', '\xe0'):
        code = msvcrt.getwch()
        return _WIN_ESCAPE_MAP.get(code)
    if ch == '\r':
        if _win_key_down(_VK_SHIFT):
            return '\x1b[13;2u'
        if _win_key_down(_VK_CONTROL):
            return '\x1b[13;5u'
        return '\r'
    if ch == '\x1b' and msvcrt.kbhit():
        seq = '\x1b'
        while msvcrt.kbhit():
            c = msvcrt.getwch()
            seq += c
            if c == '~' or c.isalpha():
                break
        if len(seq) > 1:
            return seq
    return ch


def _get_input_getch_unix() -> None | str:
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(sys.stdin.fileno())
        ch = sys.stdin.read(1)
        if ch == '\x1b':
            ch += _read_escape()
            if ch in _PASTE_MARKERS:
                return ch
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def get_input_getch() -> None | str:
    if _WINDOWS:
        return _get_input_getch_windows()
    return _get_input_getch_unix()
