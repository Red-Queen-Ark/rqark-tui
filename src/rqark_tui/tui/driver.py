from __future__ import annotations

import os
import selectors
from codecs import getincrementaldecoder

from textual._loop import loop_last
from textual._parser import ParseError
from textual._xterm_parser import XTermParser
from textual.driver import Driver
from textual.drivers.linux_driver import LinuxDriver


def tolerant_driver_class(driver_class: type[Driver]) -> type[Driver]:
    return TolerantLinuxDriver if driver_class is LinuxDriver else driver_class


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
