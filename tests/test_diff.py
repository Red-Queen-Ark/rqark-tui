import io
import time

from rich.color import Color
from rich.console import Console

from rqark_tui.tui import diff

PATCH = """diff --git a/src/app.py b/src/app.py
index 83ac1f2..9d0e4b1 100644
--- a/src/app.py
+++ b/src/app.py
@@ -12,7 +12,8 @@ def main() -> None:
     config = load()
-    run(config)
+    log.info('starting')
+    run(config)
     return None


@@ -31,3 +32,4 @@ def load() -> dict:
     return {}
+    # trailing
"""


def _colours(text: str) -> dict[str, str]:
    console = Console(file=io.StringIO(), width=80, force_terminal=True, color_system='truecolor')
    found: dict[str, str] = {}
    for segment in console.render(diff.render(text)):
        if segment.style is not None and segment.style.color is not None:
            found.setdefault(segment.text, segment.style.color.get_truecolor().hex)
    return found


def test_looks_like_diff_accepts_a_unified_diff():
    assert diff.looks_like_diff(PATCH) is True


def test_looks_like_diff_rejects_plain_tool_output():
    assert diff.looks_like_diff('total 8\ndrwxr-xr-x 2 user user 4096 .') is False
    assert diff.looks_like_diff('') is False


def test_looks_like_diff_rejects_prose_quoting_a_hunk():
    assert diff.looks_like_diff('the header reads @@ -1,2 +1,2 @@ in the spec') is False


def test_looks_like_diff_rejects_a_hunk_without_file_headers():
    assert diff.looks_like_diff('@@ -1,2 +1,2 @@\n-a\n+b\n') is False


def test_render_colours_added_and_removed_lines():
    colours = _colours(PATCH)
    assert colours["+    log.info('starting')"] == Color.parse(diff.DIFF_ADD).get_truecolor().hex
    assert colours['-    run(config)'] == Color.parse(diff.DIFF_DEL).get_truecolor().hex


def test_render_colours_hunk_headers_as_divider_rows():
    colours = _colours(PATCH)
    assert colours['@@ -12,7 +12,8 @@ def main() -> None:'] == Color.parse(diff.DIFF_HUNK).get_truecolor().hex


def test_render_keeps_context_lines_neutral():
    colours = _colours(PATCH)
    assert colours['     return None'] == Color.parse(diff.DIFF_CONTEXT).get_truecolor().hex


def test_render_drops_the_header_of_a_single_file_patch():
    rendered = diff.render(PATCH).plain
    assert 'diff --git' not in rendered
    assert 'index ' not in rendered
    assert '--- a/src/app.py' not in rendered
    assert '+++ b/src/app.py' not in rendered


def test_render_labels_each_file_of_a_multi_file_patch():
    text = '--- a/one.py\n+++ b/one.py\n@@ -1 +1 @@\n-a\n+b\n--- a/two.py\n+++ b/two.py\n@@ -1 +1 @@\n-c\n+d\n'
    rendered = diff.render(text).plain
    assert rendered.splitlines()[:2] == ['one.py', '@@ -1 +1 @@']


def test_render_marks_the_no_newline_marker():
    colours = _colours('--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n\\ No newline at end of file\n')
    assert colours['\\ No newline at end of file'] == Color.parse(diff.DIFF_META).get_truecolor().hex


def test_render_caps_a_large_patch_and_keeps_the_rest_for_the_copy_buffer():
    body = '\n'.join(f'+line {index}' for index in range(3000))
    text = f'--- a/big.txt\n+++ b/big.txt\n@@ -1,1 +1,3000 @@\n{body}\n'
    started = time.perf_counter()
    rendered = diff.render(text)
    elapsed = time.perf_counter() - started
    rows = rendered.plain.splitlines()
    assert len(rows) == diff.MAX_LINES + 1
    assert rows[-1] == '… 2601 more line(s), copy for the full patch'
    assert elapsed < 0.5
