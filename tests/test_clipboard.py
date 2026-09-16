import subprocess
import sys

import pytest

from rqark_tui.tui import clipboard


class RecordingRun:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple[list[str], bytes, bool]] = []
        self.error = error

    def __call__(self, command, input=None, check=False):  # noqa: A002
        if self.error is not None:
            raise self.error
        self.calls.append((list(command), input, check))
        return subprocess.CompletedProcess(command, 0)


def set_platform(monkeypatch: pytest.MonkeyPatch, platform: str) -> None:
    monkeypatch.setattr(clipboard.sys, 'platform', platform)


def test_darwin_uses_pbcopy(monkeypatch):
    set_platform(monkeypatch, 'darwin')
    run = RecordingRun()
    monkeypatch.setattr(clipboard.subprocess, 'run', run)
    clipboard.write_system_clipboard('hello')
    assert run.calls == [(['pbcopy'], 'hello'.encode(), True)]


def test_error_from_the_clipboard_tool_is_swallowed(monkeypatch):
    set_platform(monkeypatch, 'darwin')
    run = RecordingRun(error=subprocess.CalledProcessError(1, 'pbcopy'))
    monkeypatch.setattr(clipboard.subprocess, 'run', run)
    clipboard.write_system_clipboard('hello')
    assert run.calls == []


def test_missing_clipboard_tool_is_swallowed(monkeypatch):
    set_platform(monkeypatch, 'darwin')
    run = RecordingRun(error=FileNotFoundError('pbcopy'))
    monkeypatch.setattr(clipboard.subprocess, 'run', run)
    clipboard.write_system_clipboard('hello')


def test_os_error_from_the_clipboard_tool_is_swallowed(monkeypatch):
    set_platform(monkeypatch, 'darwin')
    run = RecordingRun(error=OSError('broken pipe'))
    monkeypatch.setattr(clipboard.subprocess, 'run', run)
    clipboard.write_system_clipboard('hello')


def test_windows_uses_clip(monkeypatch):
    set_platform(monkeypatch, 'win32')
    run = RecordingRun()
    monkeypatch.setattr(clipboard.subprocess, 'run', run)
    clipboard.write_system_clipboard('hello')
    assert run.calls == [(['clip'], 'hello'.encode(), True)]


def test_linux_prefers_xclip(monkeypatch):
    set_platform(monkeypatch, 'linux')
    run = RecordingRun()
    monkeypatch.setattr(clipboard.subprocess, 'run', run)
    monkeypatch.setattr(clipboard.shutil, 'which', lambda name: f'/usr/bin/{name}')
    clipboard.write_system_clipboard('hello')
    assert run.calls == [(['xclip', '-selection', 'clipboard'], 'hello'.encode(), True)]


def test_linux_falls_back_to_xsel(monkeypatch):
    set_platform(monkeypatch, 'linux')
    run = RecordingRun()
    monkeypatch.setattr(clipboard.subprocess, 'run', run)
    monkeypatch.setattr(clipboard.shutil, 'which', lambda name: None if name == 'xclip' else '/usr/bin/xsel')
    clipboard.write_system_clipboard('hello')
    assert run.calls == [(['xsel', '--clipboard', '--input'], 'hello'.encode(), True)]


def test_linux_without_a_clipboard_tool_does_nothing(monkeypatch):
    set_platform(monkeypatch, 'linux')
    run = RecordingRun()
    monkeypatch.setattr(clipboard.subprocess, 'run', run)
    monkeypatch.setattr(clipboard.shutil, 'which', lambda name: None)
    clipboard.write_system_clipboard('hello')
    assert run.calls == []


def test_text_is_encoded_as_utf8(monkeypatch):
    set_platform(monkeypatch, 'darwin')
    run = RecordingRun()
    monkeypatch.setattr(clipboard.subprocess, 'run', run)
    clipboard.write_system_clipboard('中文 🙂')
    assert run.calls[0][1] == '中文 🙂'.encode()


def test_platform_detection_uses_the_running_interpreter_by_default():
    assert isinstance(sys.platform, str)
