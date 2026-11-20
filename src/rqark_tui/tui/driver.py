"""Input driver that survives stdin which is not valid UTF-8.

Textual's ``LinuxDriver`` decodes stdin with a strict incremental UTF-8 decoder,
so a single stray byte — a terminal sending ``0xa9`` on its own, say — raises
``UnicodeDecodeError`` in the input thread and the app panics. The tolerant
driver below decodes with ``replace`` instead, turning the bad byte into U+FFFD.

The driver is a subclass of Textual's Linux driver, and importing that module
imports ``termios``, which does not exist on Windows. So the subclass is built
on first use, and only when the app really resolved to the Linux driver.
"""

from __future__ import annotations

import os
import selectors
from codecs import getincrementaldecoder
from functools import cache

from textual._loop import loop_last
from textual._parser import ParseError
from textual._xterm_parser import XTermParser
from textual.driver import Driver

#: Module Textual keeps its Linux driver in; checked instead of imported.
LINUX_DRIVER_MODULE = 'textual.drivers.linux_driver'


def tolerant_driver_class(driver_class: type[Driver]) -> type[Driver]:
    """``driver_class`` itself, or the tolerant replacement for the Linux driver."""
    if driver_class.__module__ != LINUX_DRIVER_MODULE or driver_class.__name__ != 'LinuxDriver':
        return driver_class
    return tolerant_linux_driver()


@cache
def tolerant_linux_driver() -> type[Driver]:
    """The tolerant Linux driver, built on first use.

    Raises:
        ImportError: Textual has no Linux driver, which happens off Linux.
    """
    from textual.drivers.linux_driver import LinuxDriver

    class TolerantLinuxDriver(LinuxDriver):
        """Linux driver that survives input which is not valid UTF-8."""

        def run_input_thread(self) -> None:
            """Wait for input and dispatch events."""
            selector = selectors.SelectSelector()
            selector.register(self.fileno, selectors.EVENT_READ)

            fileno = self.fileno
            event_read = selectors.EVENT_READ

            parser = XTermParser(self._debug)
            feed = parser.feed
            tick = parser.tick

            decode = getincrementaldecoder('utf-8')('replace').decode
            read = os.read

            def process_selector_events(selector_events: list[tuple[selectors.SelectorKey, int]], final: bool = False) -> None:
                for last, (_selector_key, mask) in loop_last(selector_events):
                    if mask & event_read:
                        unicode_data = decode(read(fileno, 1024 * 4), final=final and last)
                        if not unicode_data:
                            break
                        for event in feed(unicode_data):
                            self.process_message(event)
                for event in tick():
                    self.process_message(event)

            try:
                while not self.exit_event.is_set():
                    process_selector_events(selector.select(0.1))
                selector.unregister(self.fileno)
                process_selector_events(selector.select(0.1), final=True)

            finally:
                selector.close()
                try:
                    for _event in feed(''):
                        pass
                except EOFError, ParseError:
                    pass

    return TolerantLinuxDriver
