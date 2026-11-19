import asyncio
from pathlib import Path

import pytest
from rqark_app.config.manager import ConfigManager
from rqark_app.session.storage import CloudStorage, JSONLStorage

from rqark_tui.app import build_storage, open_app


class Probe:
    """Counts how many of the two startup reads are open at the same time."""

    def __init__(self) -> None:
        self.in_flight = 0
        self.peak = 0

    def enter(self) -> None:
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)

    def leave(self) -> None:
        self.in_flight -= 1


class SlowStorage(JSONLStorage):
    def __init__(self, path: Path, probe: Probe) -> None:
        super().__init__(path)
        self._probe = probe

    async def load(self):
        self._probe.enter()
        try:
            await asyncio.sleep(0.02)
            return []
        finally:
            self._probe.leave()


class SlowSops:
    def __init__(self, probe: Probe) -> None:
        self._probe = probe

    async def list(self) -> list:
        self._probe.enter()
        try:
            await asyncio.sleep(0.02)
            return []
        finally:
            self._probe.leave()


class FakeConfig:
    """Only the attributes ``open_app`` reads."""

    def __init__(self, directory: Path, probe: Probe) -> None:
        self.config_path = directory
        self.cloud_client = None
        self.providers: list = []
        self.sop_manager = SlowSops(probe)


async def test_sessions_and_sops_are_loaded_at_the_same_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    probe = Probe()
    monkeypatch.setattr('rqark_tui.app.build_storage', lambda _config: SlowStorage(tmp_path / 'sessions', probe))

    await open_app(FakeConfig(tmp_path, probe))

    assert probe.peak > 1


async def test_storage_is_local_without_a_cloud(tmp_path: Path):
    config = ConfigManager(str(tmp_path), source='TUI')
    await config.load()

    assert isinstance(build_storage(config), JSONLStorage)
    await config.aclose()


async def test_storage_is_the_cloud_when_one_is_configured(tmp_path: Path):
    config = ConfigManager(str(tmp_path), source='TUI')
    await config.load()
    config.cloud_client = CloudStorage.__new__(CloudStorage)

    assert isinstance(build_storage(config), CloudStorage)
    config.cloud_client = None
    await config.aclose()
