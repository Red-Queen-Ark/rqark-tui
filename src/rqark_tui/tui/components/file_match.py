import fnmatch
import os
import time
from pathlib import Path

IGNORE_NAMES = {'.git', '.hg', '.svn', '.venv', 'venv', '__pycache__', 'node_modules', 'dist', 'build', '.tox'}
IGNORE_SUFFIXES = {'.pyc', '.pyo', '.egg-info'}
MAX_DEPTH = 8
CACHE_TTL = 5.0
GITIGNORE_MAX_DEPTH = 4


class FileMatcher:
    """Matches file paths for `@` completion, one directory level at a time."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or Path.cwd()).resolve()
        self._walk_cache: dict[str, tuple[float, list[tuple[str, str, bool]]]] = {}
        self._pattern_cache: dict[str, list[tuple[bool, str, str]]] = {}
        self._root_patterns: list[tuple[bool, str, str]] = []
        base = self.root
        for _ in range(GITIGNORE_MAX_DEPTH + 1):
            ignore_file = base / '.gitignore'
            if ignore_file.is_file():
                self._root_patterns.extend((negate, pattern, '') for negate, pattern in self._parse_gitignore(ignore_file))
            if base.parent == base:
                break
            base = base.parent

    @staticmethod
    def _parse_gitignore(path: Path) -> list[tuple[bool, str]]:
        patterns: list[tuple[bool, str]] = []
        try:
            lines = path.read_text(encoding='utf-8').splitlines()
        except OSError:
            return patterns
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            negate = line.startswith('!')
            if negate:
                line = line[1:].strip()
            if line:
                patterns.append((negate, line))
        return patterns

    @staticmethod
    def _match_pattern(pattern: str, rel: str) -> bool:
        if pattern.endswith('/'):
            base = pattern[:-1]
            if rel == base or rel.startswith(base + '/'):
                return True
            return any(fnmatch.fnmatch(part, base) for part in rel.split('/'))
        if '/' in pattern:
            return fnmatch.fnmatch(rel, pattern)
        return any(fnmatch.fnmatch(part, pattern) for part in rel.split('/'))

    @staticmethod
    def _ignored(patterns: list[tuple[bool, str, str]], rel: str) -> bool:
        if any(part in IGNORE_NAMES for part in rel.split('/')):
            return True
        if any(rel.endswith(suffix) for suffix in IGNORE_SUFFIXES):
            return True
        ignored = False
        for negate, pattern, anchor in patterns:
            if anchor:
                if rel == anchor:
                    target = ''
                elif rel.startswith(anchor + '/'):
                    target = rel[len(anchor) + 1:]
                else:
                    continue
            else:
                target = rel
            if FileMatcher._match_pattern(pattern, target):
                ignored = not negate
        return ignored

    def _patterns_for(self, search_dir: Path) -> list[tuple[bool, str, str]]:
        key = str(search_dir)
        cached = self._pattern_cache.get(key)
        if cached is not None:
            return cached
        patterns = list(self._root_patterns)
        chain: list[Path] = []
        base = search_dir
        while base != self.root and base.parent != base:
            chain.append(base)
            base = base.parent
        for directory in reversed(chain):
            ignore_file = directory / '.gitignore'
            if ignore_file.is_file():
                anchor = directory.relative_to(self.root).as_posix()
                patterns.extend((negate, pattern, anchor) for negate, pattern in self._parse_gitignore(ignore_file))
        self._pattern_cache[key] = patterns
        return patterns

    def _walk(self, base_dir: str) -> list[tuple[str, str, bool]]:
        cached = self._walk_cache.get(base_dir)
        if cached is not None and time.time() - cached[0] < CACHE_TTL:
            return cached[1]
        search_dir = (self.root / base_dir).resolve() if base_dir else self.root
        patterns = self._patterns_for(search_dir)
        result: list[tuple[str, str, bool]] = []
        if search_dir.is_dir():
            self._walk_recursive(search_dir, base_dir, '', patterns, result, MAX_DEPTH)
        self._walk_cache[base_dir] = (time.time(), result)
        return result

    def _walk_recursive(
        self,
        directory: Path,
        base_dir: str,
        rel_prefix: str,
        patterns: list[tuple[bool, str, str]],
        result: list[tuple[str, str, bool]],
        depth: int,
    ) -> None:
        try:
            entries = sorted(os.scandir(directory), key=lambda e: (not e.is_dir(), e.name.lower()))
        except OSError:
            return
        for entry in entries:
            is_dir = entry.is_dir()
            display = f'{rel_prefix}{entry.name}'
            if is_dir:
                display += '/'
            rel = f'{base_dir}{display}'
            if self._ignored(patterns, rel):
                continue
            if is_dir:
                result.append((display, rel, True))
                if depth > 0:
                    self._walk_recursive(Path(entry.path), base_dir, f'{rel_prefix}{entry.name}/', patterns, result, depth - 1)
            else:
                result.append((display, rel, False))

    def matches(self, prefix: str) -> list[tuple[str, str, bool]]:
        """Return (display_name, full_rel_path, is_dir) matches under the base dir."""
        if '/' in prefix:
            slash_idx = prefix.rfind('/')
            base_dir, name_filter = prefix[: slash_idx + 1], prefix[slash_idx + 1:]
        else:
            base_dir, name_filter = '', prefix
        matches_list = self._walk(base_dir)
        if name_filter:
            needle = name_filter.lower()
            matches_list = [m for m in matches_list if os.path.basename(m[0].rstrip('/')).lower().startswith(needle)]
        return matches_list
