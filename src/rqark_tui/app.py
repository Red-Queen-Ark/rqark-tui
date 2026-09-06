import asyncio

from rqark_app.agent.manager import AgentManager
from rqark_app.app import AgentApp
from rqark_app.session.storage import JSONLStorage

from rqark_tui.config.default import AGENTS
from rqark_tui.config.manager import ConfigManager
from rqark_tui.tui import AgentTUI


async def _main() -> None:
    config_mgr = ConfigManager('./.rqark')
    config_mgr.load()

    agent_mgr = AgentManager(AGENTS)

    storage = JSONLStorage(config_mgr.config_path / 'sessions')
    app = AgentApp(config_mgr.providers, storage)
    await app.session_mgr.load()

    tui = AgentTUI()
    tui.set_agent_name(agent_mgr.agent.name)
    tui.set_model_name(app.provider_mgr.provider.name)
    await tui.run()


def main():
    asyncio.run(_main())
