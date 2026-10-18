import pytest
from rqark_app.sop.types import Sop

from rqark_tui.tui.commands import COMMANDS, slash_entries


def test_commands_table_is_complete():
    assert [name for name, _ in COMMANDS] == ['/clear', '/close', '/compact', '/new', '/stop', '/models', '/agents']


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


def test_unknown_prefix_returns_nothing():
    assert slash_entries('/zzz') == []


def test_text_without_a_leading_slash_returns_nothing():
    assert slash_entries('clear') == []
    assert slash_entries('') == []


def test_match_is_case_sensitive():
    assert slash_entries('/C') == []


def sop(slug: str = 'trip-itinerary', title: str = 'Trip itinerary') -> Sop:
    from rqark_app.sop.types import LOCAL_SOURCE

    return Sop(slug, title, '# Trip itinerary', LOCAL_SOURCE)


def test_sops_are_listed_after_the_built_in_commands():
    entries = slash_entries('/', [sop()])
    assert [value for _label, value in entries] == [name for name, _ in COMMANDS] + ['/trip-itinerary']


def test_a_sop_label_carries_its_title():
    label, value = slash_entries('/trip', [sop()])[0]
    assert value == '/trip-itinerary'
    assert label == '/trip-itineraryTrip itinerary'


def test_a_sop_prefix_filters_its_entry():
    assert slash_entries('/trip', [sop()])[-1][1] == '/trip-itinerary'
    assert slash_entries('/tripx', [sop()]) == []


def test_a_built_in_command_wins_a_name_clash():
    assert [value for _label, value in slash_entries('/clear', [sop('clear', 'Clear')])] == ['/clear']
