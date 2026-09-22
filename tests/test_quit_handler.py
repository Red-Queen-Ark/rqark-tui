from unittest.mock import patch

from textual import events
from textual.actions import SkipAction
from textual.widgets import Button

from rqark_tui.tui import AgentTUI
from rqark_tui.tui.components.dialog import YesNoDialog
from rqark_tui.tui.components.footer import ChatInput
from rqark_tui.tui.components.main import MessagePane
from rqark_tui.tui.components.quit_handler import QuitHandler


def escape_event() -> events.Key:
    return events.Key('escape', '\x1b')


async def press_escape(pilot, times: int) -> None:
    for _ in range(times):
        await pilot.press('escape')
        await pilot.pause()


async def open_quit_dialog(pilot, tui: AgentTUI) -> None:
    await pilot.press('ctrl+e')
    await pilot.pause()
    assert tui._quit_dialog_open is True


def test_escape_exit_count_defaults_to_three():
    assert QuitHandler.ESCAPE_EXIT_COUNT == 3


async def test_escape_presses_are_counted_up_to_the_threshold():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        with patch.object(tui, 'call_later') as call_later:
            tui.on_key(escape_event())
            assert tui._escape_presses == 1
            assert call_later.call_count == 0
            tui.on_key(escape_event())
            assert tui._escape_presses == 2
            assert call_later.call_count == 0
            tui.on_key(escape_event())
            assert tui._escape_presses == 0
            assert call_later.call_count == 1
            assert call_later.call_args.args[0] == tui.action_quit


async def test_other_keys_reset_the_escape_counter():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        tui.on_key(escape_event())
        tui.on_key(escape_event())
        assert tui._escape_presses == 2
        tui.on_key(events.Key('a', 'a'))
        assert tui._escape_presses == 0


async def test_note_escape_counts_presses_handled_by_a_child_widget():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        with patch.object(tui, 'call_later') as call_later:
            for _ in range(3):
                tui.note_escape()
            assert call_later.call_count == 1
            assert tui._escape_presses == 0


def test_ctrl_q_binding_is_removed():
    tui = AgentTUI()
    assert 'ctrl+q' not in tui._bindings.key_to_bindings


def test_ctrl_e_is_bound_to_quit():
    tui = AgentTUI()
    actions = [binding.action for binding in tui._bindings.key_to_bindings.get('ctrl+e', [])]
    assert actions == ['quit']


def test_no_app_binding_swallows_the_input_keys():
    """Ctrl+W belongs to the chat input (delete word) and Ctrl+E to the quit action."""
    tui = AgentTUI()
    assert 'ctrl+w' not in tui._bindings.key_to_bindings
    quit_actions = [binding.action for binding in tui._bindings.key_to_bindings.get('ctrl+e', [])]
    assert quit_actions == ['quit']


async def test_single_escape_keeps_focus_in_the_input():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        chat = tui.query_one(ChatInput)
        chat.text = 'draft'
        await press_escape(pilot, 1)
        assert chat.has_focus is True
        assert chat.text == 'draft'
        assert tui._quit_dialog_open is False
        assert tui._escape_presses == 1


async def test_two_escapes_do_not_open_the_dialog():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await press_escape(pilot, 2)
        assert tui._quit_dialog_open is False


async def test_three_escapes_open_the_quit_dialog_and_keep_input_focus():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        chat = tui.query_one(ChatInput)
        await press_escape(pilot, 3)
        assert tui._quit_dialog_open is True
        assert isinstance(tui.screen, YesNoDialog)
        assert tui._escape_presses == 0
        assert chat.has_focus is True


async def test_escape_outside_the_input_counts_towards_the_threshold():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        pane = tui.query_one(MessagePane)
        pane.focus()
        await pilot.pause()
        await press_escape(pilot, 3)
        assert tui._quit_dialog_open is True


async def test_escape_that_closes_a_popup_does_not_count_towards_quitting():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        chat = tui.query_one(ChatInput)
        assert chat.has_focus is True
        await pilot.press('/')
        await pilot.pause()
        await press_escape(pilot, 1)
        assert tui._escape_presses == 0
        await press_escape(pilot, 2)
        assert tui._quit_dialog_open is False


async def test_ctrl_e_opens_the_dialog_and_ctrl_e_again_quits():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await open_quit_dialog(pilot, tui)
        assert tui._exit is False
        await pilot.press('ctrl+e')
        await pilot.pause()
        assert tui._exit is True


async def test_escape_dismisses_the_dialog_without_quitting():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await press_escape(pilot, 3)
        await press_escape(pilot, 1)
        assert tui._quit_dialog_open is False
        assert tui._exit is False


async def test_no_button_dismisses_without_quitting():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await open_quit_dialog(pilot, tui)
        tui.screen.query_one('#no', Button).press()
        await pilot.pause()
        assert tui._quit_dialog_open is False
        assert tui._exit is False


async def test_yes_button_quits():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await open_quit_dialog(pilot, tui)
        tui.screen.query_one('#yes', Button).press()
        await pilot.pause()
        assert tui._exit is True


async def test_dialog_starts_with_the_yes_button_focused():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await open_quit_dialog(pilot, tui)
        assert tui.screen.focused.id == 'yes'


async def test_action_quit_skips_while_the_dialog_is_open():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await open_quit_dialog(pilot, tui)
        try:
            await tui.action_quit()
        except SkipAction:
            pass
        else:
            raise AssertionError('action_quit should skip while the dialog is open')


async def test_pending_quit_push_is_not_scheduled_twice():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        tui._quit_pending = True
        with patch.object(tui, 'push_screen') as push_screen:
            await tui.action_quit()
        assert push_screen.call_count == 0
        assert tui._quit_pending is True


async def test_push_quit_dialog_is_idempotent_when_already_open():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await open_quit_dialog(pilot, tui)
        with patch.object(tui, 'push_screen') as push_screen:
            tui._push_quit_dialog()
        assert push_screen.call_count == 0


async def test_chat_input_keeps_focus_after_the_dialog_closes():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        await open_quit_dialog(pilot, tui)
        await press_escape(pilot, 1)
        assert tui._quit_dialog_open is False
        assert tui.query_one(ChatInput).has_focus is True


async def test_typing_after_a_dismissed_dialog_still_reaches_the_input():
    tui = AgentTUI()
    async with tui.run_test(size=(40, 100)) as pilot:
        await pilot.pause()
        chat = tui.query_one(ChatInput)
        await open_quit_dialog(pilot, tui)
        await press_escape(pilot, 1)
        await pilot.press('h', 'i')
        await pilot.pause()
        assert chat.text == 'hi'
