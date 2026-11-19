import json

import pytest

from rqark_tui.tui import theme
from rqark_tui.tui.theme import DEFAULT_THEME, REQUIRED_TOKENS, ThemeError, load_theme, resolve_name, theme_names, use_theme

#: Tokens that paint a surface rather than text, so contrast does not apply.
BACKGROUND_TOKENS = ('bg', 'surface', 'border', 'selection', 'code_bg')


def _contrast(first: str, second: str) -> float:
    def luminance(colour: str) -> float:
        value = colour.lstrip('#')
        channels = [int(value[index : index + 2], 16) / 255 for index in (0, 2, 4)]
        linear = [channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_the_three_dark_themes_ship() -> None:
    assert theme_names() == ['eva', 'matrix', 'redqueen']


@pytest.mark.parametrize('name', theme_names())
def test_every_theme_defines_every_token(name: str) -> None:
    loaded = load_theme(name)
    assert loaded.name == name
    assert set(loaded.colors) == set(REQUIRED_TOKENS)


@pytest.mark.parametrize('name', theme_names())
def test_every_text_token_reaches_4_5_to_1_on_the_background(name: str) -> None:
    loaded = load_theme(name)
    background = loaded.color('bg')
    for token in REQUIRED_TOKENS:
        if token in BACKGROUND_TOKENS:
            continue
        assert _contrast(loaded.color(token), background) >= 4.5, f'{name}: {token}'


@pytest.mark.parametrize('name', theme_names())
def test_selected_text_stays_legible(name: str) -> None:
    loaded = load_theme(name)
    assert _contrast(loaded.color('fg'), loaded.color('selection')) >= 4.5


@pytest.mark.parametrize('name', theme_names())
def test_diff_sides_are_distinguishable(name: str) -> None:
    loaded = load_theme(name)
    assert loaded.color('diff_add') != loaded.color('diff_del')
    assert _contrast(loaded.color('diff_add'), loaded.color('bg')) >= 4.5
    assert _contrast(loaded.color('diff_del'), loaded.color('bg')) >= 4.5


def test_tokens_become_dashed_css_variables() -> None:
    variables = load_theme('matrix').variables()
    assert variables['rq-bg'] == '#000703'
    assert variables['rq-fg-muted'] == load_theme('matrix').color('fg_muted')


def test_unknown_theme_names_every_alternative() -> None:
    with pytest.raises(ThemeError) as caught:
        load_theme('solarized')
    for name in theme_names():
        assert name in str(caught.value)


def test_a_theme_missing_a_token_is_rejected(tmp_path, monkeypatch) -> None:
    broken = {'name': 'broken', 'label': 'Broken', 'colors': {'bg': '#000000'}}
    (tmp_path / 'broken.json').write_text(json.dumps(broken))
    monkeypatch.setattr(theme, 'files', lambda _package: tmp_path)
    load_theme.cache_clear()
    try:
        with pytest.raises(ThemeError) as caught:
            load_theme('broken')
        assert 'missing colour tokens' in str(caught.value)
    finally:
        load_theme.cache_clear()


def test_resolve_name_prefers_the_argument_then_the_environment(monkeypatch) -> None:
    monkeypatch.delenv('RQARK_THEME', raising=False)
    assert resolve_name() == DEFAULT_THEME
    assert resolve_name('matrix') == 'matrix'
    monkeypatch.setenv('RQARK_THEME', 'eva')
    assert resolve_name() == 'eva'
    assert resolve_name('matrix') == 'matrix'


def test_resolve_name_falls_back_when_the_name_is_unknown(monkeypatch) -> None:
    monkeypatch.delenv('RQARK_THEME', raising=False)
    assert resolve_name('nope') == DEFAULT_THEME


def test_use_theme_swaps_what_the_renderers_read() -> None:
    original = theme.active_theme()
    try:
        use_theme(load_theme('eva'))
        assert theme.active_theme().name == 'eva'
    finally:
        use_theme(original)


async def test_the_theme_command_switches_the_palette():
    from rqark_tui.tui import AgentTUI

    tui = AgentTUI(theme='redqueen')
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        tui._switch_theme('eva')
        await pilot.pause()
        assert theme.active_theme().name == 'eva'
        assert tui.screen.styles.background.hex.lower() == '#1a0000'


async def test_the_theme_command_rejects_an_unknown_name():
    from rqark_tui.tui import AgentTUI

    tui = AgentTUI(theme='matrix')
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        tui._switch_theme('solarized')
        await pilot.pause()
        assert theme.active_theme().name == 'matrix'
