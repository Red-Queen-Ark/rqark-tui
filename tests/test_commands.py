import pytest

from rqark_tui.tui.commands import COMMANDS, slash_entries


def test_commands_table_is_complete():
    assert [name for name, _ in COMMANDS] == ['/clear', '/close', '/compact', '/new', '/stop', '/models', '/agents', '/default']


@pytest.mark.parametrize('name,description', COMMANDS)
def test_every_command_matches_its_own_prefix(name, description):
    assert slash_entries(name) == [(f'{name:<9}{description}', name)]


def test_slash_alone_lists_every_command():
    entries = slash_entries('/')
    assert len(entries) == len(COMMANDS)
    assert [value for _label, value in entries] == [name for name, _ in COMMANDS]


def test_labels_are_padded_for_alignment():
    label, value = slash_entries('/c')[0]
    assert label == '/clear   Clear the current conversation'
    assert label.startswith(f'{value:<9}')


def test_prefix_filters_commands():
    assert [value for _label, value in slash_entries('/m')] == ['/models']
    assert [value for _label, value in slash_entries('/a')] == ['/agents']
    assert [value for _label, value in slash_entries('/d')] == ['/default']


def test_unknown_prefix_returns_nothing():
    assert slash_entries('/zzz') == []


def test_text_without_a_leading_slash_returns_nothing():
    assert slash_entries('clear') == []
    assert slash_entries('') == []


def test_match_is_case_sensitive():
    assert slash_entries('/C') == []
