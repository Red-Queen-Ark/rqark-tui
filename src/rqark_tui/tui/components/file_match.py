import fnmatch
import os
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

IGNORE_NAMES = frozenset({'.git', '.hg', '.svn', '.venv', 'venv', '__pycache__', 'node_modules', 'dist', 'build', '.tox'})
IGNORE_SUFFIXES = ('.pyc', '.pyo', '.egg-info')
MAX_DEPTH = 8
CACHE_TTL = 5.0
GITIGNORE_MAX_DEPTH = 4

PATH_REL = 0
NAME_ANY = 1
LEAF_DIR = 2
LITERAL_DIR = 3

M_ALWAYS = 0
M_NAME = 1
M_LEAF_DIR = 2
M_PATH = 3
M_LITERAL = 4
M_ANCHORED = 5


class _Rule(NamedTuple):
    negate: bool
    kind: int
    base: str
    regex: re.Pattern[str] | None
    anchor: str
    tail: str


class _Plan(NamedTuple):
    negate: bool
    kind: int
    base: str
    regex: re.Pattern[str] | None
    anchor: str
    tail: str
    root: bool
    mode: int


@lru_cache(maxsize=4096)
def _compile(pattern: str) -> re.Pattern[str]:
    return re.compile(fnmatch.translate(pattern))


def _rule(negate: bool, pattern: str, anchor: str) -> _Rule:
    tail = anchor + '/' if anchor else ''
    if pattern.endswith('/'):
        base = pattern[:-1]
        if '/' in base:
            return _Rule(negate, LITERAL_DIR, base, None, anchor, tail)
        return _Rule(negate, LEAF_DIR, base, _compile(base), anchor, tail)
    if '/' in pattern:
        return _Rule(negate, PATH_REL, '', _compile(pattern), anchor, tail)
    return _Rule(negate, NAME_ANY, '', _compile(pattern), anchor, tail)


class FileMatcher:
    """Matches file paths for `@` completion, one directory level at a time."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or Path.cwd()).resolve()
        self._walk_cache: dict[str, tuple[float, list[tuple[str, str, bool]], list[str]]] = {}
        self._pattern_cache: dict[str, list[_Rule]] = {}
        self._root_patterns: list[_Rule] = []
        base = self.root
        for _ in range(GITIGNORE_MAX_DEPTH + 1):
            ignore_file = base / '.gitignore'
            if ignore_file.is_file():
                self._root_patterns.extend(_rule(negate, pattern, '') for negate, pattern in self._parse_gitignore(ignore_file))
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
    def _plan_for(rules: list[_Rule], head: str) -> tuple[list[_Plan], bool]:
        parts = [part for part in head.split('/') if part]
        root = not head
        base_ignored = any(part in IGNORE_NAMES for part in parts)
        plan: list[_Plan] = []
        for rule in rules:
            regex = rule.regex
            if rule.anchor:
                plan.append(_Plan(rule.negate, rule.kind, rule.base, regex, rule.anchor, rule.tail, root, M_ANCHORED))
            elif rule.kind == PATH_REL:
                plan.append(_Plan(rule.negate, rule.kind, rule.base, regex, '', '', root, M_PATH))
            elif rule.kind == LITERAL_DIR:
                plan.append(_Plan(rule.negate, rule.kind, rule.base, regex, '', '', root, M_LITERAL))
            elif rule.kind == NAME_ANY:
                matched = regex is not None and any(regex.fullmatch(part) for part in parts)
                plan.append(_Plan(rule.negate, rule.kind, rule.base, regex, '', '', root, M_ALWAYS if matched else M_NAME))
            elif head.startswith(rule.base + '/') or (regex is not None and any(regex.fullmatch(part) for part in parts)):
                plan.append(_Plan(rule.negate, rule.kind, rule.base, regex, '', '', root, M_ALWAYS))
            else:
                plan.append(_Plan(rule.negate, rule.kind, rule.base, regex, '', '', root, M_LEAF_DIR))
        return plan, base_ignored

    @staticmethod
    def _anchored(plan: _Plan, rel: str) -> bool:
        if rel == plan.anchor:
            target = ''
        elif rel.startswith(plan.tail):
            target = rel[len(plan.tail) :]
        else:
            return False
        regex = plan.regex
        if plan.kind == PATH_REL:
            return regex is not None and regex.match(target) is not None
        if plan.kind == LITERAL_DIR:
            return target == plan.base or target.startswith(plan.base + '/')
        if plan.kind == LEAF_DIR:
            if target == plan.base or target.startswith(plan.base + '/'):
                return True
            return regex is not None and any(regex.fullmatch(part) for part in target.split('/'))
        return regex is not None and any(regex.fullmatch(part) for part in target.split('/'))

    @staticmethod
    def _ignored(plan: list[_Plan], rel: str, name: str, base_ignored: bool) -> bool:
        if base_ignored or name in IGNORE_NAMES or rel.endswith(IGNORE_SUFFIXES):
            return True
        hit = False
        negate = False
        for item in plan:
            mode = item.mode
            if mode == M_ALWAYS:
                matched = True
            elif mode == M_NAME:
                regex = item.regex
                matched = regex is not None and regex.fullmatch(name) is not None
            elif mode == M_LEAF_DIR:
                regex = item.regex
                matched = (item.root and name == item.base) or (regex is not None and regex.fullmatch(name) is not None)
            elif mode == M_LITERAL:
                matched = rel == item.base or rel.startswith(item.base + '/')
            elif mode == M_PATH:
                regex = item.regex
                matched = regex is not None and regex.match(rel) is not None
            else:
                matched = FileMatcher._anchored(item, rel)
            if matched:
                hit = True
                negate = item.negate
        return hit and not negate

    def _patterns_for(self, search_dir: Path) -> list[_Rule]:
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
                patterns.extend(_rule(negate, pattern, anchor) for negate, pattern in self._parse_gitignore(ignore_file))
        self._pattern_cache[key] = patterns
        return patterns

    def _walk(self, base_dir: str) -> tuple[list[tuple[str, str, bool]], list[str]]:
        cached = self._walk_cache.get(base_dir)
        now = time.time()
        if cached is not None and now - cached[0] < CACHE_TTL:
            return cached[1], cached[2]
        search_dir = (self.root / base_dir).resolve() if base_dir else self.root
        rules = self._patterns_for(search_dir)
        result: list[tuple[str, str, bool]] = []
        names: list[str] = []
        if search_dir.is_dir():
            self._walk_recursive(str(search_dir), base_dir, '', rules, result, names, MAX_DEPTH)
        self._walk_cache[base_dir] = (now, result, names)
        return result, names

    def _walk_recursive(self, directory: str, base_dir: str, display_prefix: str, rules: list[_Rule], result: list[tuple[str, str, bool]], names: list[str], depth: int) -> None:
        try:
            with os.scandir(directory) as scan:
                found = [(entry.name, entry.is_dir(), entry.path) for entry in scan]
        except OSError:
            return
        found.sort(key=lambda item: (not item[1], item[0].lower()))
        plan, base_ignored = self._plan_for(rules, base_dir + display_prefix)
        ignored = self._ignored
        for name, is_dir, path in found:
            display = f'{display_prefix}{name}/' if is_dir else display_prefix + name
            rel = base_dir + display
            if ignored(plan, rel, name, base_ignored):
                continue
            result.append((display, rel, is_dir))
            names.append(name.lower())
            if is_dir and depth > 0:
                self._walk_recursive(path, base_dir, display, rules, result, names, depth - 1)

    def matches(self, prefix: str) -> list[tuple[str, str, bool]]:
        """Return (display_name, full_rel_path, is_dir) matches under the base dir."""
        if '/' in prefix:
            slash_idx = prefix.rfind('/')
            base_dir, name_filter = prefix[: slash_idx + 1], prefix[slash_idx + 1 :]
        else:
            base_dir, name_filter = '', prefix
        entries, names = self._walk(base_dir)
        if not name_filter:
            return entries
        needle = name_filter.lower()
        return [entry for entry, name in zip(entries, names) if name.startswith(needle)]
