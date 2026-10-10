from dataclasses import dataclass, field
from typing import Protocol

from rqark_app.types.session import Session
from rqark_core.types.tool import PlanItem
from textual.worker import Worker

from rqark_tui.tui.components.main import MessagePane


def session_uuid(agent_id: str = '', path: tuple[str, ...] = ()) -> str:
    """The app session an event belongs to.

    The root agent id is ``'<agent name>:<session uuid>'``; a subagent reports the
    root as the first entry of its ``path``.
    """
    root = path[0] if path else agent_id
    return root.partition(':')[2]


class SessionHandler(Protocol):
    """The per-session bridge to the agent app that the TUI drives."""

    async def chat(self, text: str, images: list[str] | None = None) -> None: ...

    async def command(self, command: str) -> str | None: ...

    async def revert(self, message_id: str) -> Session | None:
        """Trim the session back to the user message ``message_id`` (None when impossible)."""
        ...

    async def close(self) -> None:
        """Release the session (its stored transcript is dropped with its tab)."""
        ...


@dataclass
class ChatSession:
    """One chat tab: its pane, the app session behind it and its running state.

    ``pane`` keeps its own transcript while hidden, so a session keeps streaming
    in the background and is fully rendered the moment its tab is selected.
    """

    key: str
    ordinal: int
    pane: MessagePane
    handler: SessionHandler | None = None
    session_id: str | None = None
    title: str = ''
    plan: list[PlanItem] = field(default_factory=list)
    busy: bool = False
    draft: str = ''
    worker: 'Worker[None] | None' = None

    @property
    def label(self) -> str:
        """The tab label: the generated title once there is one, else an ordinal."""
        return self.title or f'Session {self.ordinal}'
