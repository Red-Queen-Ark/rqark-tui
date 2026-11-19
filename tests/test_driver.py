import os
import threading

from textual.drivers.headless_driver import HeadlessDriver
from textual.drivers.linux_driver import LinuxDriver
from textual.message import Message

from rqark_tui.tui.driver import TolerantLinuxDriver, tolerant_driver_class


class Harness(TolerantLinuxDriver):
    def __init__(self, fileno: int) -> None:
        self.fileno = fileno
        self._debug = False
        self.exit_event = threading.Event()
        self.seen: list[Message] = []

    def process_message(self, message: Message) -> None:
        self.seen.append(message)


def test_linux_driver_is_swapped() -> None:
    assert tolerant_driver_class(LinuxDriver) is TolerantLinuxDriver
    assert tolerant_driver_class(HeadlessDriver) is HeadlessDriver


def test_invalid_utf8_does_not_kill_the_input_thread() -> None:
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
