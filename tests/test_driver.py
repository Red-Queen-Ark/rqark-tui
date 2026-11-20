import os
import subprocess
import sys
import threading

from textual.driver import Driver
from textual.drivers.headless_driver import HeadlessDriver
from textual.message import Message

from rqark_tui.tui.driver import LINUX_DRIVER_MODULE, tolerant_driver_class, tolerant_linux_driver


def test_linux_driver_is_swapped() -> None:
    class FakeLinuxDriver(Driver):
        pass

    FakeLinuxDriver.__module__ = LINUX_DRIVER_MODULE
    FakeLinuxDriver.__qualname__ = 'LinuxDriver'
    FakeLinuxDriver.__name__ = 'LinuxDriver'

    assert tolerant_driver_class(FakeLinuxDriver) is tolerant_linux_driver()
    assert tolerant_driver_class(HeadlessDriver) is HeadlessDriver


def test_the_linux_driver_module_is_not_imported_from_the_package() -> None:
    probe = 'import sys, rqark_tui.tui.driver; print("termios" in sys.modules)'
    out = subprocess.run([sys.executable, '-c', probe], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == 'False'


def test_invalid_utf8_does_not_kill_the_input_thread() -> None:
    driver_class = tolerant_linux_driver()

    class Harness(driver_class):
        def __init__(self, fileno: int) -> None:
            self.fileno = fileno
            self._debug = False
            self.exit_event = threading.Event()
            self.seen: list[Message] = []

        def process_message(self, message: Message) -> None:
            self.seen.append(message)

    read_fd, write_fd = os.pipe()
    driver = Harness(read_fd)
    thread = threading.Thread(target=driver.run_input_thread)
    thread.start()
    os.write(write_fd, b'a\xa9b')
    os.close(write_fd)
    driver.exit_event.set()
    thread.join(5)
    assert not thread.is_alive()
    os.close(read_fd)
