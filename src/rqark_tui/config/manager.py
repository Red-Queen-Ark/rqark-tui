from pathlib import Path
from rqark_tui.utils.io import IO_Helper
from rqark_core.types.provider import Provider
from rqark_app.types.agent import BaseAgent
from collections.abc import Sequence

class ConfigManager:
    def __init__(self, config_path: str):
        self.io_helper = IO_Helper()
        self.config_path = Path(config_path)
        self.agents: Sequence[BaseAgent] = []
        self.providers: Sequence[Provider] = []
        
    def load(self):
        self.config_path.mkdir(parents=True, exist_ok=True)
        self._local_agents()
        
    def _local_agents(self):
        path = self.config_path / 'agents'
        if path.is_dir():
            path.glob('*.yml')
        
    def _local_provider(self):
        path = self.config_path / 'provider.yml'
        providers = self.io_helper.read(path)