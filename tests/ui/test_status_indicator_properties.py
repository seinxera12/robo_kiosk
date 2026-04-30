"""
Property-based tests for StatusIndicator.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 5.1, 5.2**

Uses pytest-qt (qtbot fixture) and hypothesis for property-based testing.
"""

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from PyQt6.QtCore import QAbstractAnimation

from client.ui.status_indicator import StatusIndicator


# ---------------------------------------------------------------------------
# Property 6: Status label and border color match state
# Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6
# ---------------------------------------------------------------------------

@given(status=st.sampled_from(["listening", "recording", "transcribing", "thinking", "speaking", "idle"]))
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_status_label_and_border_match_state(qtbot, status):
    """
    **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**
    For any status string, after set_status(status), the label text SHALL match
    the expected label and the stylesheet SHALL contain the expected color for
    both text color and border color.
    """
    widget = StatusIndicator()
    qtbot.addWidget(widget)

    expected = {
        "listening":    ("🟢  Listening",    "#a6e3a1"),
        "recording":    ("🔴  Recording",    "#f38ba8"),
        "transcribing": ("⏳  Transcribing", "#f9e2af"),
        "thinking":     ("🟡  Processing",   "#f9e2af"),
        "speaking":     ("🔵  Speaking",     "#89b4fa"),
        "idle":         ("⚪  Idle",          "#6c7086"),
    }

    widget.set_status(status)

    label_text, color = expected[status]
    assert widget.status_label.text() == label_text
    stylesheet = widget.status_label.styleSheet()
    assert color in stylesheet
    # Border should also contain the color
    assert f"border: 1px solid {color}" in stylesheet


# ---------------------------------------------------------------------------
# Property 7: Pulse animation running for recording/speaking
# Validates: Requirements 5.1
# ---------------------------------------------------------------------------

@given(status=st.sampled_from(["recording", "speaking"]))
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_pulse_animation_running_for_active_states(qtbot, status):
    """
    **Validates: Requirements 5.1**
    For any status in {recording, speaking}, after set_status(status),
    the QPropertyAnimation SHALL be in the Running state.
    """
    widget = StatusIndicator()
    qtbot.addWidget(widget)
    widget.set_status(status)
    assert widget._pulse_anim.state() == QAbstractAnimation.State.Running


# ---------------------------------------------------------------------------
# Property 8: Pulse stops and opacity restores on inactive states
# Validates: Requirements 5.2
# ---------------------------------------------------------------------------

@given(
    active=st.sampled_from(["recording", "speaking"]),
    inactive=st.sampled_from(["listening", "thinking", "transcribing", "idle"])
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_pulse_stops_and_opacity_restores_on_inactive(qtbot, active, inactive):
    """
    **Validates: Requirements 5.2**
    For any transition from an active pulse state to an inactive state,
    after set_status(inactive_state), the QPropertyAnimation SHALL NOT be
    in the Running state AND QGraphicsOpacityEffect.opacity() SHALL equal 1.0.
    """
    widget = StatusIndicator()
    qtbot.addWidget(widget)
    widget.set_status(active)
    assert widget._pulse_anim.state() == QAbstractAnimation.State.Running
    widget.set_status(inactive)
    assert widget._pulse_anim.state() != QAbstractAnimation.State.Running
    assert widget._opacity_effect.opacity() == 1.0
