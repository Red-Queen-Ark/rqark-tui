import asyncio
from pathlib import Path

import pytest
from rqark_app.config.manager import ConfigManager
from rqark_app.session.storage import CloudStorage, JSONLStorage

from rqark_tui.app import build_app, build_storage, load_workspace
from rqark_tui.tui import AgentTUI
from rqark_tui.tui.components.footer import ChatInput
from rqark_tui.tui.components.main import MessagePane
from rqark_tui.tui.theme import active_theme


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

    async def load(self, ids=None):
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
    """Only the attributes ``load_workspace`` reads."""

    def __init__(self, directory: Path, probe: Probe) -> None:
        self.config_path = directory
        self.cwd_hash = 'cwd'
        self.dir_cache = EmptyDirCache()
        self.sop_manager = SlowSops(probe)


class EmptyDirCache:
    def get_session_ids(self, _cwd_hash: str) -> list[str]:
        return []


async def test_sessions_and_sops_are_loaded_at_the_same_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    probe = Probe()
    config = FakeConfig(tmp_path, probe)
    app = build_app(ConfigManager(str(tmp_path), source='TUI'))
    monkeypatch.setattr(app.session_mgr, 'storage', SlowStorage(tmp_path / 'sessions', probe))

    restored, sops = await load_workspace(config, app)

    assert probe.peak > 1
    assert restored == []
    assert sops == []


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


async def test_a_session_is_on_screen_before_the_loader_answers():
    started = asyncio.Event()
    release = asyncio.Event()

    async def loader():
        started.set()
        await release.wait()
        return [('uuid-1', 'Restored', [], '')], []

    tui = AgentTUI()
    tui.load_startup(loader)
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        assert len(tui.sessions) == 1
        assert tui.query_one(MessagePane).is_empty

        await started.wait()
        release.set()
        await pilot.pause()
        await pilot.pause()

        assert [session.title for session in tui.sessions] == ['Restored']


async def test_the_placeholder_stays_when_nothing_is_restored():
    release = asyncio.Event()

    async def loader():
        await release.wait()
        return [], []

    tui = AgentTUI()
    tui.load_startup(loader)
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        placeholder = tui.active_key
        assert len(tui.sessions) == 1

        release.set()
        await pilot.pause()
        await pilot.pause()

        assert [session.key for session in tui.sessions] == [placeholder]


async def test_a_failing_loader_still_leaves_a_session_to_type_in():
    async def loader():
        raise RuntimeError('cloud is down')

    tui = AgentTUI()
    tui.load_startup(loader)
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await pilot.pause()

        assert len(tui.sessions) == 1


async def test_sops_arrive_with_the_loader():
    class Sop:
        slug = 'demo'
        title = 'Demo'

    async def loader():
        return [], [Sop()]

    tui = AgentTUI()
    tui.load_startup(loader)
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await pilot.pause()

        assert [sop.slug for sop in tui.sops] == ['demo']


async def test_bootstrap_fills_the_interface_in_after_the_first_frame(tmp_path: Path):
    from rqark_tui.app import Startup, bootstrap

    (tmp_path / 'providers.yml').write_text('- name: local\n  model_name: m\n  api_key: k\n  api_base: http://127.0.0.1:1/v1\n  priority: 1\n', encoding='utf-8')
    startup = Startup()

    tui = AgentTUI()
    tui.load_startup(lambda: bootstrap(tui, startup, config_dir=tmp_path))
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        while startup.app is None:
            await pilot.pause(0.05)
        await pilot.pause()
        assert startup.app is not None
        assert startup.config_mgr is not None
        assert len(tui.sessions) == 1


async def test_a_placeholder_with_text_is_not_thrown_away():
    release = asyncio.Event()

    async def loader():
        await release.wait()
        return [('uuid-1', 'Restored', [], '')], []

    tui = AgentTUI()
    tui.load_startup(loader)
    async with tui.run_test(size=(40, 100)) as pilot:
        chat = tui.query_one(ChatInput)
        await pilot.pause()
        chat.text = 'hello'
        await pilot.press('enter')
        await pilot.pause()

        release.set()
        await pilot.pause()
        await pilot.pause()

        assert [session.title for session in tui.sessions] == ['', 'Restored']


async def test_the_placeholder_can_chat_once_the_factory_is_set():
    release = asyncio.Event()

    async def loader():
        await release.wait()
        return [], []

    class Bridge:
        def __init__(self) -> None:
            self.chats: list[str] = []

        async def chat(self, text, images=None) -> None:
            self.chats.append(text)

    bridge = Bridge()

    tui = AgentTUI()
    tui.load_startup(loader)
    async with tui.run_test(size=(40, 100)) as pilot:
        chat = tui.query_one(ChatInput)
        await pilot.pause()
        placeholder = tui.active_session
        assert placeholder is not None
        assert placeholder.handler is None

        tui.set_session_factory(lambda _key, _session_id: bridge)
        assert placeholder.handler is bridge

        chat.text = 'hello'
        await pilot.press('enter')
        await pilot.pause()
        while not bridge.chats:
            await pilot.pause(0.05)
        assert bridge.chats == ['hello']

        release.set()
        await pilot.pause()


async def test_text_sent_before_the_factory_is_set_is_kept():
    release = asyncio.Event()

    async def loader():
        await release.wait()
        return [], []

    tui = AgentTUI()
    tui.load_startup(loader)
    async with tui.run_test(size=(40, 100)) as pilot:
        chat = tui.query_one(ChatInput)
        await pilot.pause()
        chat.text = 'hello'
        await pilot.press('enter')
        await pilot.pause()

        assert chat.text == 'hello'
        assert tui.active_session is not None
        assert tui.active_session.pane.is_empty

        release.set()
        await pilot.pause()


class FakeClient:
    def __init__(self, entries: list[dict] | None = None, error: Exception | None = None) -> None:
        self.entries = entries or []
        self.error = error
        self.written: list[tuple[str, object]] = []

    async def list_user_config(self) -> list[dict]:
        if self.error is not None:
            raise self.error
        return list(self.entries)

    async def set_user_config(self, key: str, value: object) -> dict:
        if self.error is not None:
            raise self.error
        self.written.append((key, value))
        return {'key': key, 'value': value}


async def test_the_stored_theme_is_read_back():
    from rqark_tui.app import theme_setting

    client = FakeClient([{'key': 'memory.event_log', 'value': True}, {'key': 'tui.theme', 'value': 'matrix'}])

    assert await theme_setting(client)[0]() == 'matrix'


async def test_an_unknown_stored_theme_is_ignored():
    from rqark_tui.app import theme_setting

    assert await theme_setting(FakeClient([{'key': 'tui.theme', 'value': 'solarized'}]))[0]() is None


async def test_a_missing_stored_theme_reads_as_none():
    from rqark_tui.app import theme_setting

    assert await theme_setting(FakeClient())[0]() is None


async def test_the_theme_is_written_under_its_setting_key():
    from rqark_tui.app import THEME_SETTING, theme_setting

    client = FakeClient()
    await theme_setting(client)[1]('eva')

    assert client.written == [(THEME_SETTING, 'eva')]


async def test_picking_a_theme_saves_it():
    saved: list[str] = []

    async def saver(name: str) -> None:
        saved.append(name)

    tui = AgentTUI(theme='redqueen')
    tui.set_theme_saver(saver)
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        tui._switch_theme('matrix')
        while not saved:
            await pilot.pause(0.05)
        assert saved == ['matrix']


async def test_applying_a_theme_without_persist_does_not_save_it():
    saved: list[str] = []

    async def saver(name: str) -> None:
        saved.append(name)

    tui = AgentTUI(theme='redqueen')
    tui.set_theme_saver(saver)
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        tui.apply_theme('eva')
        await pilot.pause(0.1)
        assert saved == []


async def test_a_failing_saver_keeps_the_theme_on_screen():
    async def saver(_name: str) -> None:
        raise RuntimeError('cloud is down')

    tui = AgentTUI(theme='redqueen')
    tui.set_theme_saver(saver)
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        tui._switch_theme('eva')
        await pilot.pause(0.2)
        assert active_theme().name == 'eva'
