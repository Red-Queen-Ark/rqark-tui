from typing import cast

from rqark_app.config.manager import ConfigManager
from rqark_app.session.manager import SessionManager
from rqark_app.types.session import Session
from rqark_core.types.chat import UserMessage

from rqark_tui.app import restored_sessions


class FakeDirCache:
    def __init__(self, session_ids: list[str]) -> None:
        self.session_ids = session_ids
        self.removed: list[str] = []

    def get_session_ids(self, cwd_hash: str) -> list[str]:
        return list(self.session_ids)

    def remove_session_id(self, cwd_hash: str, session_id: str) -> None:
        self.removed.append(session_id)


class FakeConfigManager:
    def __init__(self, session_ids: list[str]) -> None:
        self.cwd_hash = 'cwd-hash'
        self.dir_cache = FakeDirCache(session_ids)


class FakeSessionManager:
    def __init__(self, sessions: list[Session]) -> None:
        self.sessions = {session.uuid: session for session in sessions}

    async def get(self, session_id: str) -> Session | None:
        return self.sessions.get(session_id)


def config_with(*session_ids: str) -> ConfigManager:
    return cast(ConfigManager, FakeConfigManager(list(session_ids)))


def manager_with(*sessions: Session) -> SessionManager:
    return cast(SessionManager, FakeSessionManager(list(sessions)))


def stored(uuid: str = 'uuid-1', title: str = 'stored title', history: list | None = None) -> Session:
    session = Session(uuid=uuid)
    session.title = title
    session.history = history if history is not None else [UserMessage('old question')]
    return session


async def test_a_directory_that_remembers_nothing_restores_nothing():
    config = config_with()
    assert await restored_sessions(config, manager_with(stored())) == []


async def test_a_remembered_session_is_restored_with_its_transcript():
    config = config_with('uuid-1')
    restored = await restored_sessions(config, manager_with(stored()))
    assert [(uuid, title) for uuid, title, _messages in restored] == [('uuid-1', 'stored title')]
    assert [message.content for message in restored[0][2]] == ['old question']


async def test_every_remembered_session_is_restored_in_order():
    config = config_with('uuid-2', 'uuid-1')
    restored = await restored_sessions(config, manager_with(stored('uuid-1'), stored('uuid-2')))
    assert [uuid for uuid, _title, _messages in restored] == ['uuid-2', 'uuid-1']


async def test_a_remembered_session_without_a_transcript_is_forgotten():
    config = config_with('uuid-gone', 'uuid-1')
    restored = await restored_sessions(config, manager_with(stored()))
    assert [uuid for uuid, _title, _messages in restored] == ['uuid-1']
    assert config.dir_cache.removed == ['uuid-gone']


async def test_an_empty_session_is_restored_as_an_empty_transcript():
    config = config_with('uuid-1')
    restored = await restored_sessions(config, manager_with(stored(title='', history=[])))
    assert restored == [('uuid-1', '', [])]
