from typing import cast

from rqark_app.config.manager import ConfigManager
from rqark_app.types.agent import BaseAgent

from rqark_tui.app import load_agent_manager


class FakeAgent(BaseAgent):
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = ''
        self.prompts = []
        self.tools = []


class FakeConfigManager:
    def __init__(self, agents: list[BaseAgent]) -> None:
        self.agents = agents


def config_with(*agents: BaseAgent) -> ConfigManager:
    return cast(ConfigManager, FakeConfigManager(list(agents)))


def test_the_agents_are_the_ones_the_config_directory_holds():
    manager = load_agent_manager(config_with(FakeAgent('Configured')))
    assert [agent.name for agent in manager.agents] == ['Configured']
    assert manager.agent.name == 'Configured'


def test_every_configured_agent_is_offered_for_switching():
    manager = load_agent_manager(config_with(FakeAgent('First'), FakeAgent('Second')))
    assert [agent.name for agent in manager.agents] == ['First', 'Second']
