# Intent Classification Fix — Bugfix Design

## Overview

The intent classifier in `server/llm/intent_classifier.py` uses a two-tier pipeline:
**Tier 1** (keyword rules) and **Tier 2** (embedding cosine similarity). When a short
conversational input such as `こんにちは` ("Hello" in Japanese) is given, Tier 1 finds
no keyword matches and returns `GENERAL` with confidence 0.4 — below the 0.7 short-circuit
threshold. Tier 2 then computes cosine similarity against pre-computed anchor embeddings and
incorrectly selects `SEARCH` at 84.20% confidence, triggering the full web-search pipeline
(Ollama query reformulation → SearXNG → result formatting) for what should be a simple
conversational reply.

The fix adds a **Tier 0 conversational guard** that intercepts known greetings and
acknowledgements before any keyword or embedding logic runs, and optionally adds a
**Tier 3 LLM-based classification** for genuinely ambiguous inputs that neither the keyword
nor embedding tier can resolve confidently. The LLM tier must fall back gracefully to the
existing approach on failure or timeout, preserving the <15 ms target for the
keyword/embedding path.

---

## Glossary

- **Bug_Condition (C)**: The condition that triggers the bug — the input is a greeting or
  conversational acknowledgement that contains no building/search keywords, yet the embedding
  tier returns `SEARCH` with confidence ≥ 0.6.
- **Property (P)**: The desired behavior when the bug condition holds — the classifier SHALL
  return `GENERAL` intent.
- **Preservation**: All existing correct classifications (BUILDING, SEARCH, GENERAL for
  non-greeting inputs) that must remain unchanged after the fix.
- **`IntentClassifier.classify`**: The public method in
  `server/llm/intent_classifier.py` that routes a user query to one of three intents.
- **`_keyword_classify`**: Tier 1 — counts keyword hits from `_BUILDING_KEYWORDS` and
  `_SEARCH_KEYWORDS`; returns `GENERAL` with confidence 0.4 when no keywords match.
- **`_embedding_classify`**: Tier 2 — computes max cosine similarity between the query
  embedding and pre-computed anchor embeddings for each intent.
- **Tier 0 guard**: The new conversational pre-filter to be added before Tier 1.
- **Tier 3 LLM tier**: Optional new tier that calls a local LLM for genuinely ambiguous
  inputs; falls back to the existing result on failure/timeout.
- **`isBugCondition(X)`**: Pseudocode predicate that returns `true` for inputs that trigger
  the misclassification bug.
- **`classify`** / **`F`**: The original (unfixed) classifier function.
- **`classify'`** / **`F'`**: The fixed classifier function.

---

## Bug Details

### Bug Condition

The bug manifests when a user sends a short conversational input (greeting or
acknowledgement) that contains no building or search keywords. The `_keyword_classify`
method returns `GENERAL` with confidence 0.4, which is below the 0.7 short-circuit
threshold. Control then passes to `_embedding_classify`, which selects the intent whose
anchor set has the highest max cosine similarity. For short, semantically ambiguous inputs
the SEARCH anchors (e.g. "what is the weather today") happen to score higher than the
GENERAL anchors, so `SEARCH` is returned with high confidence.

**Formal Specification:**

```
FUNCTION isBugCondition(X)
  INPUT:  X of type UserInput { text: string }
  OUTPUT: boolean

  text_lower ← X.text.lower().strip()

  // Condition A: input is a known greeting
  isGreeting ← text_lower IN {
    "こんにちは", "おはよう", "おはようございます", "こんばんは", "やあ",
    "hello", "hi", "hey", "good morning", "good afternoon",
    "good evening", "good night", "howdy", "greetings", "sup", "yo"
  }

  // Condition B: input is a conversational acknowledgement
  isAcknowledgement ← text_lower IN {
    "thanks", "thank you", "okay", "ok", "sure", "yes", "no",
    "got it", "understood", "alright", "cool", "great", "nice",
    "ありがとう", "ありがとうございます", "わかりました", "はい",
    "いいえ", "なるほど", "そうですか", "了解"
  }

  // Condition C: short phrase with no keyword hits (catches unlisted greetings)
  noKeywordHits ← (count of _BUILDING_KEYWORDS in text_lower) = 0
               AND (count of _SEARCH_KEYWORDS   in text_lower) = 0
  isShortPhrase ← word_count(text_lower) ≤ 3 AND char_count(text_lower) ≤ 15

  RETURN (isGreeting OR isAcknowledgement)
         OR (isShortPhrase AND noKeywordHits)
END FUNCTION
```

### Examples

| Input | Current (buggy) result | Expected result |
|---|---|---|
| `こんにちは` | SEARCH 84.20% (embedding) | GENERAL |
| `hello` | SEARCH (embedding) | GENERAL |
| `hi` | SEARCH (embedding) | GENERAL |
| `おはよう` | SEARCH (embedding) | GENERAL |
| `ありがとう` | SEARCH (embedding) | GENERAL |
| `okay` | SEARCH (embedding) | GENERAL |
| `今日の天気は` | SEARCH (keyword) ✓ | SEARCH (unchanged) |
| `トイレはどこですか` | BUILDING (keyword) ✓ | BUILDING (unchanged) |
| `tell me a joke` | GENERAL (default/embedding) ✓ | GENERAL (unchanged) |

---

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**

- Genuine search queries (e.g. "what is the weather today", "今日の天気は",
  "latest news about the election") MUST continue to be classified as `SEARCH`.
- Building navigation queries (e.g. "where is the cafeteria", "トイレはどこですか",
  "which floor is the gym on") MUST continue to be classified as `BUILDING`.
- Keyword short-circuit at confidence ≥ 0.7 MUST continue to bypass the embedding tier.
- History carry-over for short follow-up queries MUST continue to work.
- The embedding tier MUST continue to resolve genuinely ambiguous non-greeting queries.
- The LLM tier (if added) MUST fall back to the existing keyword/embedding result on any
  failure or timeout, leaving the existing path completely unaffected.

**Scope:**

All inputs that do NOT satisfy `isBugCondition(X)` must be completely unaffected by this
fix. This includes:

- Any query containing at least one `_BUILDING_KEYWORDS` or `_SEARCH_KEYWORDS` hit.
- Longer conversational queries (> 3 words / > 15 characters) that are not in the explicit
  greeting/acknowledgement lists.
- Queries resolved by the history carry-over mechanism.

---

## Hypothesized Root Cause

Based on the bug description and code inspection, the most likely causes are:

1. **Missing conversational pre-filter (primary cause)**: There is no Tier 0 guard that
   intercepts known greetings and acknowledgements before the keyword or embedding stages.
   The keyword stage correctly returns `GENERAL` with low confidence (0.4), but the
   0.7 threshold is not met, so the embedding stage is reached.

2. **Weak GENERAL anchor set**: The `_GENERAL_ANCHORS` list contains longer, more
   semantically rich phrases ("tell me a joke", "explain quantum computing"). Short
   greetings have low cosine similarity to these anchors. The SEARCH anchors, being
   shorter on average ("what is the weather today"), happen to be geometrically closer
   to short inputs in the embedding space.

3. **No confidence floor for keyword-GENERAL results**: When `_keyword_classify` returns
   `GENERAL` with confidence 0.4, there is no mechanism to prevent the embedding tier from
   overriding it with a different intent. A keyword-derived `GENERAL` result should carry
   more weight than an embedding result for inputs with zero keyword hits.

4. **Embedding tier threshold too low for short inputs**: The 0.6 confidence threshold for
   the embedding tier does not account for the fact that short inputs produce unreliable
   cosine similarity scores — any anchor can score above 0.6 for a 1–3 word input.

---

## Correctness Properties

Property 1: Bug Condition — Conversational Inputs Classified as GENERAL

_For any_ input `X` where `isBugCondition(X)` returns `true` (i.e. the input is a greeting,
acknowledgement, or short phrase with no keyword hits), the fixed `classify'` function
SHALL return `intent = GENERAL`, regardless of what the embedding tier would have returned.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**

---

Property 2: Preservation — Non-Conversational Input Behavior Unchanged

_For any_ input `X` where `isBugCondition(X)` returns `false` (i.e. the input is NOT a
greeting or short no-keyword phrase), the fixed `classify'` function SHALL produce the same
`intent` as the original `classify` function, preserving all existing BUILDING, SEARCH, and
GENERAL routing behavior.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**

---

## Fix Implementation

### Changes Required

**File:** `server/llm/intent_classifier.py`

**Primary change — Tier 0 conversational guard:**

Add a `_CONVERSATIONAL_INPUTS` set and a `_is_conversational` helper, then insert a Tier 0
check at the top of `classify()` before the keyword stage.

```
_CONVERSATIONAL_INPUTS: set[str] = {
    # English greetings
    "hello", "hi", "hey", "howdy", "greetings", "sup", "yo",
    "good morning", "good afternoon", "good evening", "good night",
    # English acknowledgements
    "thanks", "thank you", "okay", "ok", "sure", "yes", "no",
    "got it", "understood", "alright", "cool", "great", "nice",
    # Japanese greetings
    "こんにちは", "おはよう", "おはようございます", "こんばんは",
    "やあ", "どうも",
    # Japanese acknowledgements
    "ありがとう", "ありがとうございます", "わかりました", "はい",
    "いいえ", "なるほど", "そうですか", "了解",
}

FUNCTION _is_conversational(text_lower: str) -> bool:
  IF text_lower IN _CONVERSATIONAL_INPUTS:
    RETURN true
  // Short phrase with no keyword hits — likely a greeting variant
  IF word_count(text_lower) ≤ 3
     AND char_count(text_lower) ≤ 15
     AND no _BUILDING_KEYWORDS hit
     AND no _SEARCH_KEYWORDS hit:
    RETURN true
  RETURN false
```

**Insertion point in `classify()`:**

```
// NEW: Tier 0 — conversational guard (before keyword stage)
IF _is_conversational(text_lower):
  RETURN ClassificationResult(
    intent    = GENERAL,
    confidence = 0.95,
    method    = "conversational_guard",
    matched_keywords = [],
  )
```

**Secondary change — strengthen GENERAL anchor set:**

Add short greeting-like phrases to `_GENERAL_ANCHORS` so the embedding tier is less likely
to misclassify greeting variants not in the explicit list:

```
_GENERAL_ANCHORS additions:
  "hello", "hi there", "good morning",
  "thanks", "okay", "sure",
  "こんにちは", "ありがとう", "はい",
```

**Optional change — Tier 3 LLM classification:**

Add an optional `_llm_classify(text)` method that calls a local LLM (e.g. via the existing
Ollama client) with a structured prompt asking for intent classification. This tier is
invoked only when the embedding tier returns confidence < 0.6 (i.e. the default fallback
path). It MUST:

- Use a hard timeout (e.g. 2 s) to avoid blocking the response pipeline.
- Return `None` on any exception or timeout, causing `classify()` to fall through to the
  existing `GENERAL` default.
- Never be invoked for inputs already handled by Tier 0 or Tier 1.

```
FUNCTION _llm_classify(text: str) -> ClassificationResult | None:
  TRY with timeout=2s:
    prompt ← build_classification_prompt(text)
    response ← ollama_client.generate(prompt)
    intent ← parse_intent_from_response(response)
    RETURN ClassificationResult(intent, confidence=0.8, method="llm", ...)
  ON timeout OR exception:
    RETURN None
```

**Specific Changes Summary:**

1. **Add `_CONVERSATIONAL_INPUTS` set** at module level alongside the existing keyword sets.
2. **Add `_is_conversational(text_lower)` helper method** to `IntentClassifier`.
3. **Insert Tier 0 guard** at the top of `classify()`, before the `_keyword_classify` call.
4. **Extend `_GENERAL_ANCHORS`** with short greeting phrases to improve embedding accuracy.
5. **(Optional) Add `_llm_classify` method** and wire it into `classify()` as Tier 3,
   invoked only when embedding confidence < 0.6, with graceful fallback.

---

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that
demonstrate the bug on the unfixed code to confirm the root cause; then verify the fix
works correctly and preserves all existing behavior.

---

### Exploratory Bug Condition Checking

**Goal:** Surface counterexamples that demonstrate the bug BEFORE implementing the fix.
Confirm or refute the root cause analysis. If refuted, re-hypothesize.

**Test Plan:** Instantiate `IntentClassifier` without an embedder (keyword-only) and with a
mock embedder that returns the same cosine similarity distribution as the real model. Run
classification on greeting inputs and assert the result is `GENERAL`. These tests WILL FAIL
on the unfixed code, confirming the bug.

**Test Cases:**

1. **Japanese greeting test**: Classify `こんにちは` — expect `GENERAL`, observe `SEARCH`
   (will fail on unfixed code).
2. **English greeting test**: Classify `hello` — expect `GENERAL`, observe `SEARCH`
   (will fail on unfixed code).
3. **Short acknowledgement test**: Classify `okay` — expect `GENERAL`, observe `SEARCH`
   (will fail on unfixed code).
4. **Japanese acknowledgement test**: Classify `ありがとう` — expect `GENERAL`, observe
   `SEARCH` (will fail on unfixed code).
5. **Short no-keyword phrase test**: Classify `やあ` (2 chars, no keywords) — expect
   `GENERAL`, observe `SEARCH` (may fail on unfixed code).

**Expected Counterexamples:**

- `classify("こんにちは").intent == SEARCH` (confidence ≈ 0.84)
- `classify("hello").intent == SEARCH`
- Root cause confirmed: embedding tier overrides keyword-derived `GENERAL` for short inputs.

---

### Fix Checking

**Goal:** Verify that for all inputs where the bug condition holds, the fixed function
returns `GENERAL`.

**Pseudocode:**

```
FOR ALL X WHERE isBugCondition(X) DO
  result ← classify'(X.text)
  ASSERT result.intent = GENERAL
  ASSERT result.method IN {"conversational_guard", "keyword", "default"}
END FOR
```

---

### Preservation Checking

**Goal:** Verify that for all inputs where the bug condition does NOT hold, the fixed
function produces the same intent as the original function.

**Pseudocode:**

```
FOR ALL X WHERE NOT isBugCondition(X) DO
  ASSERT classify(X.text).intent = classify'(X.text).intent
END FOR
```

**Testing Approach:** Property-based testing is recommended for preservation checking
because:

- It generates many test cases automatically across the input domain.
- It catches edge cases that manual unit tests might miss (e.g. queries that happen to be
  short but contain a keyword).
- It provides strong guarantees that behavior is unchanged for all non-buggy inputs.

**Test Plan:** Observe behavior on UNFIXED code first for genuine search/building queries,
then write property-based tests capturing that behavior.

**Test Cases:**

1. **Search query preservation**: Verify `classify("what is the weather today").intent ==
   SEARCH` on unfixed code, then assert the same on fixed code.
2. **Building query preservation**: Verify `classify("where is the cafeteria").intent ==
   BUILDING` on unfixed code, then assert the same on fixed code.
3. **Japanese search preservation**: Verify `classify("今日の天気は").intent == SEARCH`
   unchanged after fix.
4. **Japanese building preservation**: Verify `classify("トイレはどこですか").intent ==
   BUILDING` unchanged after fix.
5. **Keyword short-circuit preservation**: Verify that queries with ≥ 1 keyword hit and
   confidence ≥ 0.7 still bypass the embedding tier after fix.
6. **History carry-over preservation**: Verify that short follow-up queries after a
   building turn still resolve to `BUILDING` via history carry-over.

---

### Unit Tests

- Test `_is_conversational()` with every entry in `_CONVERSATIONAL_INPUTS` — all must
  return `True`.
- Test `_is_conversational()` with genuine search/building queries — all must return
  `False`.
- Test `_is_conversational()` with short phrases (≤ 3 words, ≤ 15 chars) that have no
  keyword hits — must return `True`.
- Test `_is_conversational()` with short phrases that DO contain a keyword (e.g. "天気") —
  must return `False`.
- Test `classify()` with Tier 0 inputs — verify `method == "conversational_guard"` and
  `intent == GENERAL`.
- Test `classify()` with keyword-matched inputs — verify Tier 0 is NOT triggered.
- Test LLM tier fallback: mock the LLM client to raise a timeout; verify `classify()`
  returns the existing default `GENERAL` result unchanged.

### Property-Based Tests

- **Property 1 (Fix Checking)**: Generate random inputs from `_CONVERSATIONAL_INPUTS` plus
  short no-keyword phrases; assert `classify'(X).intent == GENERAL` for all.
- **Property 2 (Preservation)**: Generate random queries containing at least one
  `_SEARCH_KEYWORDS` entry; assert `classify'(X).intent == classify(X).intent` for all.
- **Property 3 (Preservation)**: Generate random queries containing at least one
  `_BUILDING_KEYWORDS` entry; assert `classify'(X).intent == classify(X).intent` for all.
- **Property 4 (Preservation — short keyword phrases)**: Generate short phrases (≤ 3 words)
  that contain a keyword; assert Tier 0 does NOT intercept them and the original intent is
  preserved.

### Integration Tests

- End-to-end test: send `こんにちは` through the full request pipeline; assert the
  general conversation handler is invoked and no SearXNG search is triggered.
- End-to-end test: send "what is the weather today" through the full pipeline; assert the
  web search pipeline IS triggered (regression check).
- End-to-end test: send "where is the cafeteria" through the full pipeline; assert RAG
  retrieval IS triggered (regression check).
- LLM tier integration test (if added): send an ambiguous query with the LLM tier enabled;
  assert a valid `ClassificationResult` is returned within the timeout budget.
- LLM tier fallback integration test: configure the LLM client to time out; assert the
  classifier returns a valid result via the existing keyword/embedding path.
