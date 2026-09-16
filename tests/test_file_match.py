from pathlib import Path

import pytest

from rqark_tui.tui.components import file_match
from rqark_tui.tui.components.file_match import MAX_DEPTH, FileMatcher


def build_tree(root: Path, spec: dict[str, str]) -> None:
    for relative, content in spec.items():
        path = root / relative
        if content == '' and relative.endswith('/'):
            path.mkdir(parents=True, exist_ok=True)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def displays(matcher: FileMatcher, prefix: str = '') -> list[str]:
    return [display for display, _rel, _is_dir in matcher.matches(prefix)]


def test_files_and_directories_are_listed(tmp_path):
    build_tree(tmp_path, {'a.py': 'x', 'src/b.py': 'y'})
    matcher = FileMatcher(tmp_path)
    assert displays(matcher) == ['src/', 'src/b.py', 'a.py']


def test_directories_sort_before_files(tmp_path):
    build_tree(tmp_path, {'zeta.py': 'x', 'alpha/nested.py': 'y', 'beta.py': 'z'})
    matcher = FileMatcher(tmp_path)
    assert displays(matcher) == ['alpha/', 'alpha/nested.py', 'beta.py', 'zeta.py']


def test_directory_entries_carry_a_trailing_slash_and_a_flag(tmp_path):
    build_tree(tmp_path, {'pkg/mod.py': 'x'})
    matcher = FileMatcher(tmp_path)
    entries = {display: (rel, is_dir) for display, rel, is_dir in matcher.matches('')}
    assert entries['pkg/'] == ('pkg/', True)
    assert entries['pkg/mod.py'] == ('pkg/mod.py', False)


@pytest.mark.parametrize('directory', ['.git', '.venv', '__pycache__', 'node_modules', 'dist'])
def test_generated_directories_are_ignored(tmp_path, directory):
    build_tree(tmp_path, {f'{directory}/junk.py': 'x', 'keep.py': 'y'})
    matcher = FileMatcher(tmp_path)
    assert displays(matcher) == ['keep.py']


@pytest.mark.parametrize('suffix', ['.pyc', '.pyo', '.egg-info'])
def test_compiled_artifacts_are_ignored(tmp_path, suffix):
    build_tree(tmp_path, {f'cache{suffix}': 'x', 'keep.py': 'y'})
    matcher = FileMatcher(tmp_path)
    assert displays(matcher) == ['keep.py']


def test_gitignore_hides_matching_files(tmp_path):
    build_tree(tmp_path, {'.gitignore': '*.log\nsecret/\n', 'app.log': 'x', 'secret/key.txt': 'y', 'keep.py': 'z'})
    matcher = FileMatcher(tmp_path)
    assert displays(matcher) == ['.gitignore', 'keep.py']


def test_gitignore_negation_keeps_a_file(tmp_path):
    build_tree(tmp_path, {'.gitignore': '*.log\n!important.log\n', 'app.log': 'x', 'important.log': 'y'})
    matcher = FileMatcher(tmp_path)
    assert displays(matcher) == ['.gitignore', 'important.log']


def test_gitignore_comments_and_blank_lines_are_skipped(tmp_path):
    build_tree(tmp_path, {'.gitignore': '\n# a comment\n*.log\n\n', 'app.log': 'x', 'keep.py': 'y'})
    matcher = FileMatcher(tmp_path)
    assert displays(matcher) == ['.gitignore', 'keep.py']


def test_nested_gitignore_is_not_applied_when_listing_from_the_root(tmp_path):
    build_tree(tmp_path, {'pkg/.gitignore': '*.txt\n', 'pkg/a.txt': 'x', 'b.txt': 'y'})
    matcher = FileMatcher(tmp_path)
    assert displays(matcher) == ['pkg/', 'pkg/.gitignore', 'pkg/a.txt', 'b.txt']


def test_nested_gitignore_is_applied_when_listing_inside_that_directory(tmp_path):
    build_tree(tmp_path, {'pkg/.gitignore': '*.txt\n', 'pkg/a.txt': 'x', 'pkg/b.py': 'y'})
    matcher = FileMatcher(tmp_path)
    assert displays(matcher, 'pkg/') == ['.gitignore', 'b.py']


def test_pattern_with_a_slash_matches_the_relative_path(tmp_path):
    build_tree(tmp_path, {'.gitignore': 'pkg/*.txt\n', 'pkg/a.txt': 'x', 'pkg/nested/b.txt': 'y'})
    matcher = FileMatcher(tmp_path)
    assert displays(matcher) == ['pkg/', 'pkg/nested/', '.gitignore']


def test_directory_pattern_also_matches_nested_parts(tmp_path):
    build_tree(tmp_path, {'.gitignore': 'build/\n', 'src/build/out.txt': 'x'})
    matcher = FileMatcher(tmp_path)
    assert displays(matcher) == ['src/', '.gitignore']


def test_matches_filters_on_the_name_prefix(tmp_path):
    build_tree(tmp_path, {'main.py': 'x', 'models.py': 'y', 'other.txt': 'z'})
    matcher = FileMatcher(tmp_path)
    assert displays(matcher, 'ma') == ['main.py']
    assert displays(matcher, 'M') == ['main.py', 'models.py']


def test_matches_lists_a_directory_before_filtering_inside_it(tmp_path):
    build_tree(tmp_path, {'src/a.py': 'x', 'src/b.py': 'y', 'other/c.py': 'z'})
    matcher = FileMatcher(tmp_path)
    assert displays(matcher, 'src/') == ['a.py', 'b.py']
    assert displays(matcher, 'src/a') == ['a.py']


def test_matches_for_a_missing_directory_returns_nothing(tmp_path):
    build_tree(tmp_path, {'a.py': 'x'})
    matcher = FileMatcher(tmp_path)
    assert displays(matcher, 'nope/') == []


def test_display_names_are_relative_to_the_searched_directory(tmp_path):
    build_tree(tmp_path, {'src/a.py': 'x'})
    matcher = FileMatcher(tmp_path)
    assert matcher.matches('src/') == [('a.py', 'src/a.py', False)]
    assert matcher.matches('') == [('src/', 'src/', True), ('src/a.py', 'src/a.py', False)]


def test_results_are_cached_between_calls(tmp_path, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(file_match.time, 'time', lambda: clock[0])
    build_tree(tmp_path, {'a.py': 'x'})
    matcher = FileMatcher(tmp_path)
    assert displays(matcher) == ['a.py']
    build_tree(tmp_path, {'b.py': 'y'})
    assert displays(matcher) == ['a.py']
    clock[0] += file_match.CACHE_TTL + 1
    assert displays(matcher) == ['a.py', 'b.py']


def test_deep_directories_beyond_the_depth_limit_are_skipped(tmp_path):
    deep = '/'.join(f'd{i}' for i in range(MAX_DEPTH + 3))
    build_tree(tmp_path, {f'{deep}/leaf.py': 'x'})
    matcher = FileMatcher(tmp_path)
    found = displays(matcher)
    assert 'd0/' in found
    assert not any('leaf.py' in entry for entry in found)


def test_gitignore_patterns_are_read_from_a_parent_directory(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    (tmp_path / '.gitignore').write_text('*.log\n')
    build_tree(root, {'app.log': 'x', 'keep.py': 'y'})
    matcher = FileMatcher(root)
    assert displays(matcher) == ['keep.py']


def test_root_defaults_to_the_working_directory(tmp_path, monkeypatch):
    build_tree(tmp_path, {'a.py': 'x'})
    monkeypatch.chdir(tmp_path)
    matcher = FileMatcher()
    assert matcher.root == tmp_path.resolve()
    assert displays(matcher) == ['a.py']
