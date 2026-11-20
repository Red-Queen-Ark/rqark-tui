from rqark_core.types.chat import UserMessage

from rqark_tui.tui import AgentTUI
from rqark_tui.tui.components.main import MessagePane
from rqark_tui.tui.components.splash import Splash, wordmark_lines, wordmark_width


def visible(tui: AgentTUI) -> bool:
    return tui.query_one(Splash).has_class('visible')


def test_the_wordmark_spells_the_product_name() -> None:
    assert len(wordmark_lines()) == 5
    assert wordmark_width() >= 40
    assert all(len(line) <= wordmark_width() for line in wordmark_lines())


def test_the_wordmark_is_block_art() -> None:
    assert set(''.join(wordmark_lines())) <= {'█', ' '}


async def test_a_new_session_opens_on_the_splash():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        assert visible(tui)
        assert tui.query_one(MessagePane).is_empty


async def test_the_first_message_takes_the_splash_away():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        tui.append_message('hello')
        await pilot.pause()
        assert not visible(tui)


async def test_a_restored_session_shows_its_transcript_instead_of_the_splash():
    tui = AgentTUI()
    tui.open_sessions([('stored-uuid', 'kept', [UserMessage('earlier')], '')])
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        assert not visible(tui)


async def test_switching_tabs_follows_which_session_is_empty():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        first = tui.active_key
        tui.append_message('hello')
        await pilot.pause()
        assert not visible(tui)

        tui.new_session()
        await pilot.pause()
        assert visible(tui)

        tui.select_session(first)
        await pilot.pause()
        assert not visible(tui)


async def test_clearing_a_session_brings_the_splash_back():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        tui.append_message('hello')
        await pilot.pause()
        tui.clear_messages()
        await pilot.pause()
        assert visible(tui)


async def test_the_wordmark_follows_a_theme_change():
    from rqark_tui.tui.theme import active_theme, load_theme, use_theme

    original = active_theme()
    tui = AgentTUI(theme='default')
    try:
        async with tui.run_test(size=(90, 24)) as pilot:
            await pilot.pause()
            before = {str(segment.style) for strip in tui.screen._compositor.render_strips() for segment in strip._segments if '█' in segment.text}
            assert load_theme('default').color('accent') in ' '.join(before)

            tui.apply_theme('eva')
            await pilot.pause()
            after = {str(segment.style) for strip in tui.screen._compositor.render_strips() for segment in strip._segments if '█' in segment.text}
            assert load_theme('eva').color('accent') in ' '.join(after)
            assert before != after
    finally:
        use_theme(original)
