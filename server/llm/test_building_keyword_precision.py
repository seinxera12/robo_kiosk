"""
Building Keyword Precision — Bug Condition Exploration Tests

This module contains property-based tests for the building keyword precision bugfix.

## Bug Condition (Task 1 — Exploration)

The following false positives were confirmed on UNFIXED code. Each query was
incorrectly classified as BUILDING due to ambiguous keywords in `_BUILDING_KEYWORDS`:

| Query                                    | Ambiguous hit(s)              |
|------------------------------------------|-------------------------------|
| "on the topic of climate change"         | "on the"                      |
| "located in new york"                    | "located"                     |
| "nearest hospital"                       | "nearest"                     |
| "closest airport"                        | "closest"                     |
| "store my data"                          | "store"                       |
| "shop online"                            | "shop"                        |
| "bank account"                           | "bank"                        |
| "coffee shop near me"                    | "shop", "coffee"              |
| "garden party ideas"                     | "garden"                      |
| "find the best restaurant in tokyo"      | "restaurant", "find the"      |

All 10 inputs above produce `Intent.BUILDING` on unfixed code, confirming the bug.

## Preservation Tests (Task 2)

Preservation tests verify that correct baseline behavior is unchanged after the fix.
These tests PASS on unfixed code and must continue to pass after the fix is applied.
"""

import pytest
from hypothesis import given, settings, HealthCheck
import hypothesis.strategies as st

from llm.intent_classifier import IntentClassifier, Intent


# ---------------------------------------------------------------------------
# Confirmed false-positive inputs (all produce BUILDING on unfixed code)
# ---------------------------------------------------------------------------

_FALSE_POSITIVE_INPUTS = [
    "on the topic of climate change",
    "located in new york",
    "nearest hospital",
    "closest airport",
    "store my data",
    "shop online",
    "bank account",
    "coffee shop near me",
    "garden party ideas",
    "find the best restaurant in tokyo",
]

# ---------------------------------------------------------------------------
# Unambiguous building keyword inputs (must remain BUILDING after fix)
# ---------------------------------------------------------------------------

_UNAMBIGUOUS_BUILDING_INPUTS = [
    "where is the cafeteria",
    "which floor is the gym on",
    "トイレはどこですか",
    "find the nearest toilet",
    "how do I get to the cafeteria",
    "where is the elevator",
    "which floor is the conference room",
    "where is the lobby",
    "how do I get to the parking",
    "where is the clinic",
]

# ---------------------------------------------------------------------------
# Search keyword inputs (must remain SEARCH after fix)
# ---------------------------------------------------------------------------

_SEARCH_INPUTS = [
    "what is the weather today",
    "latest news about the election",
]

# ---------------------------------------------------------------------------
# Task 1 — Bug Condition Exploration Test
# ---------------------------------------------------------------------------

@given(st.sampled_from(_FALSE_POSITIVE_INPUTS))
@settings(suppress_health_check=[HealthCheck.too_slow])
def test_false_positive_inputs_not_classified_as_building(text: str):
    """
    Property 1: Bug Condition — Ambiguous Keywords Cause False BUILDING Classifications

    **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5**

    CRITICAL: This test MUST FAIL on unfixed code — failure confirms the bug exists.
    DO NOT fix the code when this test fails.

    For all confirmed false-positive inputs, the classifier should NOT return
    Intent.BUILDING. On unfixed code, it WILL return BUILDING (confirming the bug).
    After the fix is applied, this test should PASS.
    """
    classifier = IntentClassifier(embedder=None)
    result = classifier.classify(text)
    assert result.intent != Intent.BUILDING, (
        f"False positive detected: classify({text!r}).intent == BUILDING "
        f"(matched_keywords={result.matched_keywords})"
    )


# ---------------------------------------------------------------------------
# Task 2 — Preservation Property Tests
# ---------------------------------------------------------------------------

@given(st.sampled_from(_UNAMBIGUOUS_BUILDING_INPUTS))
@settings(suppress_health_check=[HealthCheck.too_slow])
def test_unambiguous_building_inputs_classified_as_building(text: str):
    """
    Property 2a: Preservation — Unambiguous Building Queries Remain BUILDING

    **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**

    For all queries containing an unambiguous building keyword, the classifier
    must return Intent.BUILDING. This test PASSES on unfixed code and must
    continue to pass after the fix is applied.
    """
    classifier = IntentClassifier(embedder=None)
    result = classifier.classify(text)
    assert result.intent == Intent.BUILDING, (
        f"Regression detected: classify({text!r}).intent == {result.intent.value} "
        f"(expected BUILDING, matched_keywords={result.matched_keywords})"
    )


@given(st.sampled_from(_SEARCH_INPUTS))
@settings(suppress_health_check=[HealthCheck.too_slow])
def test_search_inputs_classified_as_search(text: str):
    """
    Property 2b: Preservation — Search Queries Remain SEARCH

    **Validates: Requirements 3.7, 3.8**

    For all queries containing a search keyword (and no unambiguous building keyword),
    the classifier must return Intent.SEARCH. This test PASSES on unfixed code and
    must continue to pass after the fix is applied.
    """
    classifier = IntentClassifier(embedder=None)
    result = classifier.classify(text)
    assert result.intent == Intent.SEARCH, (
        f"Regression detected: classify({text!r}).intent == {result.intent.value} "
        f"(expected SEARCH, matched_keywords={result.matched_keywords})"
    )


@pytest.mark.parametrize("text", [
    "where is the cafeteria",
    "which floor is the gym on",
    "トイレはどこですか",
    "find the nearest toilet",
    "how do I get to the cafeteria",
])
def test_specific_building_queries_classified_as_building(text: str):
    """
    Property 2c: Preservation — Specific Named Building Queries Return BUILDING

    **Validates: Requirements 3.2, 3.3, 3.4, 3.5, 3.6**

    Specific named queries that must remain BUILDING after the fix.
    """
    classifier = IntentClassifier(embedder=None)
    result = classifier.classify(text)
    assert result.intent == Intent.BUILDING, (
        f"Regression detected: classify({text!r}).intent == {result.intent.value} "
        f"(expected BUILDING, matched_keywords={result.matched_keywords})"
    )


@pytest.mark.parametrize("text", [
    "what is the weather today",
    "latest news about the election",
])
def test_specific_search_queries_classified_as_search(text: str):
    """
    Property 2d: Preservation — Specific Named Search Queries Return SEARCH

    **Validates: Requirements 3.7, 3.8**

    Specific named queries that must remain SEARCH after the fix.
    """
    classifier = IntentClassifier(embedder=None)
    result = classifier.classify(text)
    assert result.intent == Intent.SEARCH, (
        f"Regression detected: classify({text!r}).intent == {result.intent.value} "
        f"(expected SEARCH, matched_keywords={result.matched_keywords})"
    )
