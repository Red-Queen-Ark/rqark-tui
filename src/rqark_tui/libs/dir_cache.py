import hashlib
import json
import threading
from pathlib import Path


class DirCache:
    """Maps working-directory hash → session_id so reopening a project resumes the session."""

    def __init__(self, cache_path: Path | None = None) -> None:
        self._path = cache_path or (Path.home() / '.rqark' / 'dir_cache.json')
        self._lock = threading.Lock()

    def _load(self) -> dict[str, str]:
        try:
            if self._path.exists():
                return json.loads(self._path.read_text(encoding='utf-8'))
        except Exception:
            pass
        return {}

    def _save(self, data: dict[str, str]) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._path.with_suffix('.tmp')
            tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
            tmp_path.replace(self._path)
        except OSError:
            pass

    def get_session_id(self, dir_hash: str) -> str | None:
        with self._lock:
            return self._load().get(dir_hash)

    def set_session_id(self, dir_hash: str, session_id: str) -> None:
        with self._lock:
            data = self._load()
            data[dir_hash] = session_id
            self._save(data)

    @staticmethod
    def compute_hash(cwd: str | Path) -> str:
        normalized = Path(cwd).resolve()
        return hashlib.sha256(str(normalized).encode()).hexdigest()[:12]
