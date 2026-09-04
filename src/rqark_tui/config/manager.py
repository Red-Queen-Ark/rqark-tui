from collections.abc import Sequence
from pathlib import Path

from rqark_app.types.agent import BaseAgent
from rqark_core.types.provider import Provider

from rqark_tui.config.default import AGENTS, PROVIDERS
from rqark_tui.utils.io import IoHelper


class ConfigManager:
    def __init__(self, config_path: str):
        self.io_helper = IoHelper()
        self.config_path = Path(config_path)
        self.agents: Sequence[BaseAgent] = AGENTS
        self.providers: list[Provider] = []

    def load(self):
        self.config_path.mkdir(parents=True, exist_ok=True)
        self._local_provider()

    def _local_provider(self):
        path = self.config_path / 'provider.yml'
        providers = self.io_helper.read(path)
        if providers is None:
            self.io_helper.save(path, PROVIDERS)
            providers = []
        else:
            self.providers = [ Provider(**provider) for provider in providers]
