import io

from rich.console import Console
from rich.markdown import Markdown

from rqark_tui.tui.syntax import CODE_THEME, markdown, normalise_fences, resolve_language


def _colours(source: str) -> set[str]:
    console = Console(file=io.StringIO(), width=60, force_terminal=True, color_system='truecolor')
    renderable = markdown(source)
    return {str(segment.style.color) for segment in console.render(renderable) if segment.style is not None and segment.style.color is not None}


def test_resolve_language_maps_known_aliases():
    assert resolve_language('py') == 'py'
    assert resolve_language('python') == 'python'
    assert resolve_language('ts') == 'ts'
    assert resolve_language('jsonc') == 'json'
    assert resolve_language('mjs') == 'javascript'
    assert resolve_language('patch') == 'diff'
    assert resolve_language('kt') == 'kotlin'


def test_resolve_language_returns_empty_for_unknown_and_empty():
    assert resolve_language('nonsense') == ''
    assert resolve_language('') == ''


def test_normalise_fences_rewrites_an_alias():
    assert normalise_fences('```jsonc\n{"a": 1}\n```') == '```json\n{"a": 1}\n```'


def test_normalise_fences_drops_an_unknown_language():
    assert normalise_fences('```nonsense\nx\n```') == '```\nx\n```'


def test_normalise_fences_keeps_indentation_and_fence_length():
    assert normalise_fences('  ````mjs\nconst a = 1\n  ````') == '  ````javascript\nconst a = 1\n  ````'


def test_normalise_fences_ignores_text_outside_a_fence():
    text = 'run this:\n```sh\nls -la\n```\nthen stop'
    assert normalise_fences(text) == 'run this:\n```sh\nls -la\n```\nthen stop'


def test_normalise_fences_does_not_rewrite_inside_a_code_block():
    text = '```text\n```py\nnot a fence\n```\n```'
    assert normalise_fences(text) == text


def test_normalise_fences_leaves_prose_alone():
    text = 'a paragraph with `inline code` and a ``` stray marker'
    assert normalise_fences(text) == text


def test_markdown_uses_the_transcript_code_theme():
    renderable = markdown('```python\nx = 1\n```')
    assert isinstance(renderable, Markdown)
    assert renderable.code_theme == CODE_THEME


def test_an_unknown_fence_renders_without_raising():
    assert markdown('```nonsense\nselect 1\n```')


def test_a_resolved_fence_gets_token_colours():
    assert len(_colours('```python\ndef f(x):\n    return x + 1\n```')) > 2


def test_an_unresolved_fence_gets_a_single_colour():
    assert len(_colours('```nonsense\nselect 1\n```')) == 1


def test_a_jsonc_fence_highlights_as_json():
    assert _colours('```jsonc\n{"a": 1, "b": true}\n```') == _colours('```json\n{"a": 1, "b": true}\n```')
