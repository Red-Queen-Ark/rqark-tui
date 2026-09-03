import json
from pathlib import Path
import yaml

class IO_Helper:
    def read(self, path: str | Path) -> dict | None:
        _path = Path(path)
        if not _path.exists():
            return None
        file_suffix = _path.suffix
        if file_suffix == '.json':
            return self._read_json(_path)
        elif file_suffix in [ '.yml', '.yaml']:
            return self._read_yaml(_path)

    def save(self, path: str | Path, data: dict):
        _path = Path(path)
        if not _path.exists():
            return None
        file_suffix = _path.suffix
        if file_suffix == '.json':
            return self._save_json(_path, data)
        elif file_suffix in [ '.yml', '.yaml']:
            return self._save_yaml(_path, data)

    def _read_json(self, path: Path):
        json_path = Path(path)
        with json_path.open(encoding='utf-8') as f:
            return json.load(f)

    def _save_json(self, path: Path, data: dict):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _read_yaml(self, path: Path):
        yml_path = Path(path)
        try:
            with yml_path.open(encoding='utf-8') as f:
                return yaml.safe_load(f)
        except yaml.YAMLError:
            return None

    def _save_yaml(self, path: Path, data: dict):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('w', encoding='utf-8') as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False, indent=2)
