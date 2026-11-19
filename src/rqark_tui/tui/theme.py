"""Colour tokens for the TUI, loaded from the JSON files under ``themes/``.

Every colour the interface draws comes from a :class:`Theme`. A theme is one
JSON file; adding one is dropping a file in ``themes/`` and nothing else. The
stylesheets only ever name tokens (``$rq-bg``, ``$rq-accent``), so a theme is
swapped by swapping the token values, never by editing a widget.

Selection order: the name passed to :class:`~rqark_tui.tui.AgentTUI`, then
``$RQARK_THEME``, then :data:`DEFAULT_THEME`.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from importlib.resources import files

from textual.theme import Theme as TextualTheme

#: Theme used when nothing else asks for one.
DEFAULT_THEME = 'default'

#: Environment variable that overrides :data:`DEFAULT_THEME`.
THEME_ENV = 'RQARK_THEME'

#: Every token a theme file must define. ``diff_*`` and ``code_*`` are read by
#: Python renderers; the rest are read by ``styles/app.tcss``.
REQUIRED_TOKENS = (
    'bg',
    'surface',
    'border',
    'fg',
    'fg_strong',
    'fg_dim',
    'fg_muted',
    'accent',
    'user',
    'agent',
    'tool',
    'tool_dim',
    'tool_prefix',
    'system',
    'error',
    'warning',
    'selection',
    'diff_add',
    'diff_del',
    'diff_hunk',
    'diff_meta',
    'diff_context',
    'code_bg',
    'code_text',
    'code_comment',
    'code_keyword',
    'code_string',
    'code_number',
    'code_name',
    'code_operator',
)


class ThemeError(ValueError):
    """A theme file is missing, unreadable, or does not define every token."""


@dataclass(frozen=True)
class Theme:
    """One palette: a name, a human label, and the token values."""

    name: str
    label: str
    colors: Mapping[str, str]

    def color(self, token: str) -> str:
        """The value of ``token``, or :class:`KeyError` when the theme lacks it."""
        try:
            return self.colors[token]
        except KeyError:
            raise ThemeError(f'{self.name}: unknown colour token {token!r}') from None

    def variables(self) -> dict[str, str]:
        """The tokens as Textual CSS variables, i.e. ``bg`` becomes ``rq-bg``."""
        return {f'rq-{token.replace("_", "-")}': value for token, value in self.colors.items()}


def theme_names() -> list[str]:
    """Names of the bundled themes, sorted."""
    return sorted(path.name.removesuffix('.json') for path in files(f'{__package__}.themes').iterdir() if path.name.endswith('.json'))


@cache
def load_theme(name: str) -> Theme:
    """Read ``themes/<name>.json``.

    Raises:
        ThemeError: the theme does not exist, is not valid JSON, or is missing a token.
    """
    path = files(f'{__package__}.themes') / f'{name}.json'
    if not path.is_file():
        raise ThemeError(f'unknown theme {name!r}; available: {", ".join(theme_names())}')
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except ValueError as error:
        raise ThemeError(f'{name}: not valid JSON: {error}') from error
    colors = data.get('colors')
    if not isinstance(colors, dict):
        raise ThemeError(f'{name}: "colors" must be an object')
    missing = [token for token in REQUIRED_TOKENS if token not in colors]
    if missing:
        raise ThemeError(f'{name}: missing colour tokens: {", ".join(missing)}')
    return Theme(name=data.get('name', name), label=str(data.get('label', name)), colors={str(key): str(value) for key, value in colors.items()})


def resolve_name(name: str | None = None) -> str:
    """The theme to start with: the argument, then ``$RQARK_THEME``, then the default."""
    requested = name or os.environ.get(THEME_ENV) or DEFAULT_THEME
    return requested if requested in theme_names() else DEFAULT_THEME


def textual_theme(theme: Theme) -> TextualTheme:
    """The same palette as a Textual theme, so stock widgets match the tokens."""
    return TextualTheme(
        name=f'rqark-{theme.name}',
        primary=theme.color('accent'),
        secondary=theme.color('agent'),
        accent=theme.color('accent'),
        warning=theme.color('warning'),
        error=theme.color('error'),
        success=theme.color('diff_add'),
        foreground=theme.color('fg'),
        background=theme.color('bg'),
        surface=theme.color('surface'),
        panel=theme.color('surface'),
        dark=True,
        variables=theme.variables(),
    )


_active: Theme = load_theme(resolve_name())


def active_theme() -> Theme:
    """The theme the renderers paint with."""
    return _active


def use_theme(theme: Theme) -> None:
    """Make ``theme`` the one :func:`active_theme` returns."""
    global _active
    _active = theme
