"""
Property-based tests for IntentClassifier.

Task 1: Bug Condition Exploration Test
======================================
These tests are EXPECTED TO FAIL on unfixed code.
Failure confirms the bug exists: conversational inputs (greetings,
acknowledgements) are misclassified as SEARCH via the embedding tier.

CONFIRMED COUNTEREXAMPLES (run on unfixed code, 2025):
  - classify("こんにちは").intent == SEARCH  (confidence=0.99, method=embedding)
  - classify("hello").intent == SEARCH       (confidence=0.99, method=embedding)
  - classify("okay").intent == SEARCH        (confidence=0.99, method=embedding)
  - classify("ありがとう").intent == SEARCH  (confidence=0.99, method=embedding)
  - classify("hi").intent == SEARCH          (confidence=0.99, method=embedding)

Hypothesis falsifying example:
  test_conversational_inputs_classified_as_general_with_embedder(
      text='こんにちは',
  )
  AssertionError: Expected GENERAL for conversational input 'こんにちは',
  got search (confidence=0.99, method=embedding).

Root cause confirmed: Tier 1 (keyword) returns GENERAL with confidence 0.4
(below the 0.7 short-circuit threshold). Tier 2 (embedding) then overrides
with SEARCH because the SEARCH anchors happen to score higher than GENERAL
anchors for short, semantically ambiguous inputs.

Anchor layout (unfixed code):
  _BUILDING_ANCHORS: 8 items → indices 0–7
  _SEARCH_ANCHORS:   8 items → indices 8–15
  _GENERAL_ANCHORS:  8 items → indices 16–23
  Total: 24 anchors
"""

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from llm.intent_classifier import (
    Intent,
    IntentClassifier,
    _BUILDING_ANCHORS,
    _GENERAL_ANCHORS,
    _SEARCH_ANCHORS,
)

# ---------------------------------------------------------------------------
# Known conversational inputs (will be added to source in Task 3.1)
# ---------------------------------------------------------------------------

_CONVERSATIONAL_INPUTS = [
    "こんにちは",
    "hello",
    "hi",
    "おはよう",
    "ありがとう",
    "okay",
    "やあ",
    "thanks",
    "good morning",
    "hey",
]

# Anchor index boundaries (derived from source anchor lists)
_N_BUILDING = len(_BUILDING_ANCHORS)   # 8
_N_SEARCH   = len(_SEARCH_ANCHORS)     # 8
_N_GENERAL  = len(_GENERAL_ANCHORS)    # 8
_N_TOTAL    = _N_BUILDING + _N_SEARCH + _N_GENERAL  # 24


# ---------------------------------------------------------------------------
# Mock embedder that simulates the real embedding bug
# ---------------------------------------------------------------------------

class MockSearchBiasedEmbedder:
    """
    Mock embedder that returns SEARCH-biased similarities for any short input.

    Simulates the real sentence-transformer behaviour where short conversational
    inputs (greetings, acknowledgements) end up geometrically closer to the
    SEARCH anchor embeddings than to the GENERAL anchor embeddings.

    Anchor precomputation call (24 texts):
      Returns orthogonal unit vectors (identity matrix rows) so each anchor
      has a unique, well-defined direction in embedding space.

    Single-query call (1 text):
      Returns a vector whose highest component is at index _N_BUILDING (= 8),
      which corresponds to the first SEARCH anchor.  This gives cosine
      similarity ≈ 0.99 against that SEARCH anchor and ≈ 0 against all
      BUILDING and GENERAL anchors, reproducing the bug.
    """

    def encode(self, texts):
        n = len(texts)
        dim = _N_TOTAL  # 24 — must match total anchor count exactly

        if n > 1:
            # Anchor precomputation call — return orthogonal unit vectors
            embs = np.eye(n, dim)
            return embs
        else:
            # Single-query call — return a vector closest to SEARCH anchor
            # SEARCH anchors start at index _N_BUILDING (= 8)
            emb = np.zeros(dim)
            emb[_N_BUILDING]     = 0.84  # first SEARCH anchor direction
            emb[_N_BUILDING + 1] = 0.10  # second SEARCH anchor direction
            norm = np.linalg.norm(emb) + 1e-9
            return np.array([emb / norm])


# ---------------------------------------------------------------------------
# Test A: keyword-only path (no embedder)
# ---------------------------------------------------------------------------

@given(st.sampled_from(_CONVERSATIONAL_INPUTS))
@settings(max_examples=10)
def test_conversational_inputs_classified_as_general_keyword_only(text):
    """
    Property 1 (keyword-only path): For all conversational inputs, the
    classifier WITHOUT an embedder should return GENERAL.

    On unfixed code: Tier 1 returns GENERAL with confidence 0.4 (below 0.7
    threshold), then falls through to the default which also returns GENERAL.
    This test is expected to PASS even on unfixed code for the keyword-only
    path, because without an embedder the default fallback is GENERAL.

    **Validates: Requirements 1.1, 1.2, 1.3**
    """
    classifier = IntentClassifier(embedder=None)
    result = classifier.classify(text)
    assert result.intent == Intent.GENERAL, (
        f"Expected GENERAL for conversational input '{text}', "
        f"got {result.intent.value} (confidence={result.confidence:.2f}, "
        f"method={result.method})"
    )


# ---------------------------------------------------------------------------
# Test B: mock embedder path (simulates the real embedding bug)
# ---------------------------------------------------------------------------

@given(st.sampled_from(_CONVERSATIONAL_INPUTS))
@settings(max_examples=10)
def test_conversational_inputs_classified_as_general_with_embedder(text):
    """
    Property 1 (mock embedder path): For all conversational inputs, the
    classifier WITH a SEARCH-biased mock embedder should return GENERAL.

    On unfixed code: Tier 1 returns GENERAL with confidence 0.4 (below 0.7
    threshold). Tier 2 (embedding) then returns SEARCH with confidence ~0.99
    because the mock embedder places the query closest to SEARCH anchors.
    Since 0.99 >= 0.6 threshold, SEARCH is returned — THIS IS THE BUG.

    This test WILL FAIL on unfixed code, confirming the bug exists.

    Expected counterexamples (unfixed code):
      - classify("こんにちは").intent == SEARCH  (confidence ≈ 0.84–0.99)
      - classify("hello").intent == SEARCH
      - classify("okay").intent == SEARCH
      - classify("ありがとう").intent == SEARCH
      - classify("hi").intent == SEARCH

    **Validates: Requirements 1.1, 1.2, 1.3**
    """
    classifier = IntentClassifier(embedder=MockSearchBiasedEmbedder())
    result = classifier.classify(text)
    assert result.intent == Intent.GENERAL, (
        f"Expected GENERAL for conversational input '{text}', "
        f"got {result.intent.value} (confidence={result.confidence:.2f}, "
        f"method={result.method}). "
        f"BUG CONFIRMED: embedding tier overrides keyword-derived GENERAL "
        f"with SEARCH for short conversational inputs."
    )


# ===========================================================================
# Task 2: Preservation Property Tests (BEFORE implementing fix)
# ===========================================================================
#
# These tests document the CORRECT existing behavior that must be preserved
# after the fix is implemented (Task 3).
#
# Observation on UNFIXED code (keyword-only classifier, no embedder):
#   classify("what is the weather today").intent == SEARCH  ✓
#   classify("where is the cafeteria").intent == BUILDING   ✓
#   classify("今日の天気は").intent == SEARCH               ✓
#   classify("トイレはどこですか").intent == BUILDING       ✓
#   classify("which floor is the gym on").intent == BUILDING ✓
#   classify("latest news about the election").intent == SEARCH ✓
#   classify("天気 今日").intent == SEARCH                  ✓ (short phrase WITH keyword hit)
#
# All preservation tests PASS on unfixed code and MUST PASS on fixed code.
# ===========================================================================

from llm.intent_classifier import (
    _BUILDING_KEYWORDS,
    _SEARCH_KEYWORDS,
)


# ---------------------------------------------------------------------------
# Property 2a: SEARCH keyword inputs still classified as SEARCH
# ---------------------------------------------------------------------------

@given(st.sampled_from(sorted(_SEARCH_KEYWORDS)))
@settings(max_examples=20)
def test_preservation_search_keywords_still_classified_as_search(keyword):
    """
    Property 2a: Preservation — SEARCH keyword inputs unchanged.

    For any input containing at least one SEARCH keyword, the classifier
    MUST return SEARCH intent (both before and after the fix).

    This test PASSES on unfixed code and MUST PASS on fixed code.

    Observation: classify("tell me about {keyword}") → SEARCH because
    the keyword stage finds a hit and returns confidence ≥ 0.7.

    **Validates: Requirements 3.1, 3.2**
    """
    classifier = IntentClassifier(embedder=None)
    text = f"tell me about {keyword}"
    result = classifier.classify(text)
    assert result.intent == Intent.SEARCH, (
        f"Expected SEARCH for text containing keyword '{keyword}', "
        f"got {result.intent.value} (confidence={result.confidence:.2f}, "
        f"method={result.method})"
    )


# ---------------------------------------------------------------------------
# Property 2b: BUILDING keyword inputs still classified as BUILDING
# ---------------------------------------------------------------------------

@given(st.sampled_from(sorted(_BUILDING_KEYWORDS)))
@settings(max_examples=20)
def test_preservation_building_keywords_still_classified_as_building(keyword):
    """
    Property 2b: Preservation — BUILDING keyword inputs unchanged.

    For any input containing at least one BUILDING keyword, the classifier
    MUST return BUILDING intent (both before and after the fix).

    This test PASSES on unfixed code and MUST PASS on fixed code.

    Observation: classify("where is the {keyword}") → BUILDING because
    the keyword stage finds a hit and returns confidence ≥ 0.7.

    **Validates: Requirements 3.2, 3.3**
    """
    classifier = IntentClassifier(embedder=None)
    # Use "find the {keyword}" instead of "where is the {keyword}" to avoid
    # introducing "where is the" (a SEARCH keyword) into the text, which would
    # cause a tie for keywords like "どこ" that appear in both keyword sets.
    text = f"find the {keyword}"
    result = classifier.classify(text)
    assert result.intent == Intent.BUILDING, (
        f"Expected BUILDING for text containing keyword '{keyword}', "
        f"got {result.intent.value} (confidence={result.confidence:.2f}, "
        f"method={result.method})"
    )


# ---------------------------------------------------------------------------
# Property 2c: Short keyword-bearing phrases NOT intercepted by Tier 0
# ---------------------------------------------------------------------------

# Short phrases (≤ 3 words, ≤ 15 chars) that contain a SEARCH keyword hit.
# These must NOT be intercepted by the Tier 0 conversational guard.
_SHORT_SEARCH_KEYWORD_PHRASES = [
    "天気",          # 1 word, 2 chars — SEARCH keyword
    "天気 今日",     # 2 words, 5 chars — SEARCH keyword
    "今日の天気は",  # 1 word, 7 chars — SEARCH keyword
    "weather",       # 1 word, 7 chars — SEARCH keyword
    "news today",    # 2 words, 10 chars — SEARCH keyword
    "latest news",   # 2 words, 11 chars — SEARCH keyword
    "今 ニュース",   # 2 words, 6 chars — SEARCH keyword
]

# Short phrases (≤ 3 words, ≤ 15 chars) that contain a BUILDING keyword hit.
_SHORT_BUILDING_KEYWORD_PHRASES = [
    "トイレ",        # 1 word, 3 chars — BUILDING keyword
    "どこ",          # 1 word, 2 chars — BUILDING keyword
    "gym floor",     # 2 words, 9 chars — BUILDING keyword
    "find toilet",   # 2 words, 11 chars — BUILDING keyword
    "exit here",     # 2 words, 9 chars — BUILDING keyword
    "lobby",         # 1 word, 5 chars — BUILDING keyword
]

_SHORT_KEYWORD_PHRASES = _SHORT_SEARCH_KEYWORD_PHRASES + _SHORT_BUILDING_KEYWORD_PHRASES


@given(st.sampled_from(_SHORT_KEYWORD_PHRASES))
@settings(max_examples=20)
def test_preservation_short_keyword_phrases_not_intercepted_by_tier0(phrase):
    """
    Property 2c: Preservation — short keyword-bearing phrases bypass Tier 0.

    For all short phrases (≤ 3 words, ≤ 15 chars) that contain a keyword hit,
    the result MUST NOT be intercepted by Tier 0 (i.e. method != "conversational_guard").

    This ensures the Tier 0 guard does not accidentally intercept short
    keyword-bearing queries like "天気" (weather) or "トイレ" (toilet).

    Example: "天気 今日" (2 words, 5 chars) contains the SEARCH keyword "天気"
    and MUST be classified as SEARCH, not intercepted as conversational.

    This test PASSES on unfixed code (Tier 0 does not exist yet) and
    MUST PASS on fixed code (Tier 0 must not intercept keyword-bearing inputs).

    **Validates: Requirements 3.1, 3.2, 3.3**
    """
    classifier = IntentClassifier(embedder=None)
    result = classifier.classify(phrase)
    assert result.method != "conversational_guard", (
        f"Short keyword-bearing phrase '{phrase}' was incorrectly intercepted "
        f"by Tier 0 (conversational_guard). Tier 0 must NOT intercept inputs "
        f"that contain keyword hits."
    )


# ---------------------------------------------------------------------------
# Property 2d: Multi-keyword inputs get high confidence and bypass embedding
# ---------------------------------------------------------------------------

# Inputs with ≥ 2 keyword hits — should get confidence ≥ 0.7 from Tier 1
_MULTI_KEYWORD_INPUTS = [
    # SEARCH: 2+ keyword hits
    "what is the weather today",           # "weather", "today", "what is the"
    "latest news about the election",      # "latest", "news", "election"
    "今日の天気は",                         # "今日", "天気"
    "current stock price today",           # "current", "stock", "price", "today"
    "who won the match yesterday",         # "who won", "match", "yesterday"
    # BUILDING: 2+ keyword hits
    "where is the cafeteria on this floor",  # "where is", "cafeteria", "floor"
    "which floor is the gym on",             # "which floor", "gym", "floor"
    "トイレはどこですか",                    # "トイレ", "どこ", "どこですか"
    "find the nearest toilet on floor 2",    # "find the", "nearest", "toilet", "floor"
]


@given(st.sampled_from(_MULTI_KEYWORD_INPUTS))
@settings(max_examples=20)
def test_preservation_multi_keyword_inputs_high_confidence_bypass_embedding(text):
    """
    Property 2d: Preservation — keyword short-circuit for multi-keyword inputs.

    For inputs with ≥ 2 keyword hits, the classifier MUST:
      1. Return confidence ≥ 0.7 (short-circuit threshold)
      2. Use the keyword method (not embedding or default)

    This ensures multi-keyword queries bypass the embedding tier entirely,
    preserving the fast keyword short-circuit path.

    This test PASSES on unfixed code and MUST PASS on fixed code.

    **Validates: Requirements 3.3, 3.4**
    """
    classifier = IntentClassifier(embedder=None)
    result = classifier.classify(text)
    assert result.confidence >= 0.7, (
        f"Expected confidence ≥ 0.7 for multi-keyword input '{text}', "
        f"got {result.confidence:.2f} (method={result.method})"
    )
    assert result.method == "keyword", (
        f"Expected method='keyword' for multi-keyword input '{text}', "
        f"got method='{result.method}'. Multi-keyword inputs should bypass "
        f"the embedding tier via keyword short-circuit."
    )
