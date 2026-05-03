"""
Unit and property-based tests for KioskMainWindow clear session behavior.

**Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6**

Uses pytest-qt (qtbot fixture), unittest.mock, and hypothesis for property-based testing.
"""

import pytest
from unittest.mock import MagicMock, patch
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from client.ui.app import KioskMainWindow


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def window(qtbot):
    """Create a KioskMainWindow without config (no pipeline) and without fullscreen."""
    with patch.object(KioskMainWindow, 'showFullScreen', return_value=None):
        with patch.object(KioskMainWindow, '_load_stylesheet', return_value=None):
            win = KioskMainWindow(config=None)
            qtbot.addWidget(win)
            return win


# ---------------------------------------------------------------------------
# Test 1: clear_session_btn present and disabled before _on_connected()
# Validates: Requirements 4.1
# ---------------------------------------------------------------------------

def test_clear_session_btn_present_and_disabled_before_connect(window):
    """
    The clear_session_btn widget SHALL exist and be disabled before
    _on_connected() is called (i.e., before the pipeline connects).
    """
    assert hasattr(window, 'clear_session_btn'), "clear_session_btn attribute missing"
    assert not window.clear_session_btn.isEnabled(), (
        "clear_session_btn should be disabled before _on_connected()"
    )


# ---------------------------------------------------------------------------
# Test 2: clear_session_btn enabled after _on_connected()
# Validates: Requirements 4.1
# ---------------------------------------------------------------------------

def test_clear_session_btn_enabled_after_on_connected(window):
    """
    After _on_connected() fires, clear_session_btn SHALL be enabled.
    """
    # Provide a mock worker so _on_connected() doesn't fail on attribute access
    mock_worker = MagicMock()
    mock_worker.listening_enabled = False
    window._worker = mock_worker

    window._on_connected()

    assert window.clear_session_btn.isEnabled(), (
        "clear_session_btn should be enabled after _on_connected()"
    )


# ---------------------------------------------------------------------------
# Test 3: _on_clear_session clears conversation and shows system message
# Validates: Requirements 4.2, 4.5
# ---------------------------------------------------------------------------

def test_on_clear_session_clears_conversation_and_shows_system_message(window):
    """
    _on_clear_session() SHALL clear all prior messages and then display
    the system message "Session cleared — ready for new demo."
    """
    # Add some messages first
    window.conversation.add_user_message("Hello there")
    window.conversation.add_system_message("Some prior system message")

    # No worker — tests the no-worker path
    window._worker = None
    window._on_clear_session()

    plain = window.conversation.text_display.toPlainText()
    assert "Session cleared — ready for new demo." in plain, (
        "System message not found after _on_clear_session()"
    )
    # Prior messages should be gone
    assert "Hello there" not in plain, (
        "Prior user message should have been cleared"
    )
    assert "Some prior system message" not in plain, (
        "Prior system message should have been cleared"
    )


# ---------------------------------------------------------------------------
# Test 4: _on_clear_session resets worker._response_started to False
# Validates: Requirements 4.3
# ---------------------------------------------------------------------------

def test_on_clear_session_resets_worker_response_started(window):
    """
    _on_clear_session() SHALL set worker._response_started = False.
    """
    mock_worker = MagicMock()
    mock_worker._response_started = True
    mock_worker.send_session_reset = MagicMock()
    window._worker = mock_worker

    window._on_clear_session()

    assert mock_worker._response_started is False, (
        "_response_started should be reset to False after _on_clear_session()"
    )


# ---------------------------------------------------------------------------
# Test 5: _on_clear_session calls send_session_reset when worker is set
# Validates: Requirements 4.4
# ---------------------------------------------------------------------------

def test_on_clear_session_calls_send_session_reset_when_worker_set(window):
    """
    _on_clear_session() SHALL call worker.send_session_reset() when a
    worker is present.
    """
    mock_worker = MagicMock()
    mock_worker._response_started = False
    window._worker = mock_worker

    window._on_clear_session()

    mock_worker.send_session_reset.assert_called_once(), (
        "send_session_reset() should be called once when worker is set"
    )


# ---------------------------------------------------------------------------
# Test 6: _on_clear_session does not raise when worker is None
# Validates: Requirements 4.6
# ---------------------------------------------------------------------------

def test_on_clear_session_does_not_raise_when_worker_is_none(window):
    """
    _on_clear_session() SHALL not raise any exception when self._worker is None
    (i.e., when the pipeline is not connected).
    """
    window._worker = None

    try:
        window._on_clear_session()
    except Exception as exc:
        pytest.fail(
            f"_on_clear_session() raised an unexpected exception when worker is None: {exc}"
        )


# ---------------------------------------------------------------------------
# Property 9: Clear session empties conversation for any message history
# Validates: Requirements 4.2, 4.5
# ---------------------------------------------------------------------------

@given(messages=st.lists(st.text(min_size=1).filter(lambda t: t.strip()), max_size=30))
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_clear_session_empties_conversation(qtbot, messages):
    """
    Property 9: Clear session empties conversation for any message history.
    **Validates: Requirements 4.2, 4.5**

    For any sequence of N ≥ 0 messages added to ConversationWidget, after
    _on_clear_session() is called, the conversation text SHALL contain only
    the system message "Session cleared — ready for new demo." and no prior
    message content.
    """
    with patch.object(KioskMainWindow, 'showFullScreen', return_value=None):
        with patch.object(KioskMainWindow, '_load_stylesheet', return_value=None):
            win = KioskMainWindow(config=None)
            qtbot.addWidget(win)

            # Add N messages
            for msg in messages:
                win.conversation.add_user_message(msg)

            # Call clear session (no worker)
            win._worker = None
            win._on_clear_session()

            # Only the system message should remain
            plain = win.conversation.text_display.toPlainText()
            assert "Session cleared — ready for new demo." in plain, (
                "System message not found after _on_clear_session()"
            )
