"""
Property-based tests for ConversationWidget.

**Validates: Requirements 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 2.4**

Uses pytest-qt (qtbot fixture) and hypothesis for property-based testing.
"""

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from client.ui.conversation_widget import ConversationWidget, _CURSOR_CHAR


# ---------------------------------------------------------------------------
# Property 1: Highlight timer active after add_user_message()
# Validates: Requirements 1.1
# ---------------------------------------------------------------------------

@given(text=st.text(min_size=1).filter(lambda t: t.strip()))
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_highlight_timer_active_after_add_user_message(qtbot, text):
    """
    **Validates: Requirements 1.1**
    For any non-blank transcript string (at least one non-whitespace character),
    after add_user_message() is called, the highlight timer SHALL be active.
    The implementation only starts the animation when text.strip() is non-empty,
    so whitespace-only strings are intentionally excluded.
    """
    widget = ConversationWidget()
    qtbot.addWidget(widget)
    widget.add_user_message(text)
    assert widget._highlight_timer.isActive() == True


# ---------------------------------------------------------------------------
# Property 2: Highlight leaves no background after completion
# Validates: Requirements 1.1, 1.2
# ---------------------------------------------------------------------------

@given(text=st.text(min_size=1).filter(lambda t: t.strip()))
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_highlight_clears_background_after_completion(qtbot, text):
    """
    **Validates: Requirements 1.1, 1.2**
    After all 6 highlight steps fire, the timer SHALL be stopped and
    the highlight anchor SHALL be cleared (background transparent).
    """
    widget = ConversationWidget()
    qtbot.addWidget(widget)
    widget.add_user_message(text)
    # Fire all 6 steps manually
    for _ in range(6):
        widget._on_highlight_step()
    # After all steps, timer should be stopped and background transparent
    assert not widget._highlight_timer.isActive()
    assert widget._highlight_anchor is None


# ---------------------------------------------------------------------------
# Property 3: Rapid transcripts cancel previous animation
# Validates: Requirements 1.3
# ---------------------------------------------------------------------------

@given(t1=st.text(min_size=1).filter(lambda t: t.strip()), t2=st.text(min_size=1).filter(lambda t: t.strip()))
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_second_transcript_cancels_first_animation(qtbot, t1, t2):
    """
    **Validates: Requirements 1.3**
    When two messages are added in rapid succession, only one timer SHALL be
    active and the steps SHALL be reset to 6 (fresh animation for t2).
    """
    widget = ConversationWidget()
    qtbot.addWidget(widget)
    widget.add_user_message(t1)
    widget.add_user_message(t2)
    # Only one timer should be active
    assert widget._highlight_timer.isActive() == True
    # The timer is a single QTimer instance, so it can only be active once
    # Verify steps were reset to 6 (fresh animation for t2)
    assert widget._highlight_steps == 6


# ---------------------------------------------------------------------------
# Property 4: Cursor present after start_assistant_bubble()
# Validates: Requirements 2.1, 2.2
# ---------------------------------------------------------------------------

@given(st.just(None))
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_cursor_present_after_start_assistant_bubble(qtbot, _):
    """
    **Validates: Requirements 2.1, 2.2**
    After start_assistant_bubble(), the QTextEdit document SHALL contain the
    ▋ character and the blink timer SHALL be active.
    """
    widget = ConversationWidget()
    qtbot.addWidget(widget)
    widget.start_assistant_bubble()
    assert _CURSOR_CHAR in widget.text_display.toPlainText()
    assert widget._cursor_timer.isActive() == True


# ---------------------------------------------------------------------------
# Property 5: Cursor absent after finish_assistant_bubble()
# Validates: Requirements 2.3, 2.4
# ---------------------------------------------------------------------------

@given(tokens=st.lists(st.text(), max_size=20))
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_cursor_absent_after_finish_assistant_bubble(qtbot, tokens):
    """
    **Validates: Requirements 2.3, 2.4**
    After open → append N tokens → close, the QTextEdit document SHALL NOT
    contain the ▋ character and the blink timer SHALL NOT be active.
    """
    widget = ConversationWidget()
    qtbot.addWidget(widget)
    widget.start_assistant_bubble()
    for token in tokens:
        widget.append_to_last_message(token)
    widget.finish_assistant_bubble()
    assert _CURSOR_CHAR not in widget.text_display.toPlainText()
    assert not widget._cursor_timer.isActive()
