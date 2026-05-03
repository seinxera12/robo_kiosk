# Bugfix Requirements Document

## Introduction

The intent classification system in `server/llm/intent_classifier.py` incorrectly classifies simple conversational inputs — such as greetings, small talk, and short phrases — as `SEARCH` intent. This causes the full web search pipeline (query reformulation via Ollama → SearXNG search → result formatting) to be triggered for inputs that should be handled as casual conversation (`GENERAL` intent).

The confirmed example is the Japanese greeting `こんにちは` (Konnichiwa / "Hello"), which is classified as `SEARCH` with 84.20% confidence via the embedding method. This results in the query being reformulated to `hello-meaning-japanese-culture`, a SearXNG search being executed, and irrelevant web results being returned to the user instead of a simple conversational reply.

**Root cause summary:** The two-tier classifier works as follows:
1. **Tier 1 (keyword rules):** No keywords from `_BUILDING_KEYWORDS` or `_SEARCH_KEYWORDS` match `こんにちは`, so the keyword stage returns `GENERAL` with confidence 0.4 — below the 0.7 threshold required to short-circuit.
2. **Tier 2 (embedding similarity):** The sentence-transformer embedding of `こんにちは` is compared against pre-computed anchor embeddings for BUILDING, SEARCH, and GENERAL intents. The SEARCH anchors (e.g. "what is the weather today", "latest news about") happen to have higher cosine similarity to this short, ambiguous input than the GENERAL anchors do, so `SEARCH` wins at 84.20% — above the 0.6 threshold required to return the embedding result.

The fix must ensure that conversational inputs (greetings, acknowledgements, simple questions) are reliably classified as `GENERAL`, not `SEARCH`, regardless of the language used.

---

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN the user inputs a simple greeting (e.g. `こんにちは`, `hello`, `hi`, `おはよう`, `good morning`) THEN the system classifies the input as `SEARCH` intent via the embedding method

1.2 WHEN the keyword stage returns `GENERAL` with confidence below 0.7 for a short conversational input THEN the system falls through to the embedding stage, which can override the `GENERAL` classification with `SEARCH`

1.3 WHEN the embedding stage computes cosine similarity for a short or ambiguous input THEN the system selects the intent whose anchor set happens to have the highest max-similarity score, with no guard against misclassifying conversational inputs as `SEARCH`

1.4 WHEN a greeting or conversational input is misclassified as `SEARCH` THEN the system triggers the full web search pipeline: query reformulation (Ollama call) → SearXNG search → result formatting, returning irrelevant web results to the user

1.5 WHEN a Japanese greeting is misclassified as `SEARCH` THEN the system reformulates it into an English search query (e.g. `hello-meaning-japanese-culture`) and executes a web search, producing a nonsensical response

### Expected Behavior (Correct)

2.1 WHEN the user inputs a simple greeting (e.g. `こんにちは`, `hello`, `hi`, `おはよう`, `good morning`, `hey`, `やあ`) THEN the system SHALL classify the input as `GENERAL` intent

2.2 WHEN the user inputs a short conversational phrase (e.g. `thanks`, `okay`, `ありがとう`, `わかりました`, `sure`) THEN the system SHALL classify the input as `GENERAL` intent

2.3 WHEN the keyword stage returns `GENERAL` with low confidence for a short conversational input THEN the system SHALL NOT allow the embedding stage to override that classification with `SEARCH` for inputs that match known conversational patterns

2.4 WHEN the intent classifier is given a multilingual greeting or conversational input THEN the system SHALL correctly classify it as `GENERAL` regardless of the language (English, Japanese, or other)

2.5 WHEN the system classifies an input as `GENERAL` THEN the system SHALL route the input to the general conversation handler (no web search pipeline, no RAG retrieval)

### Unchanged Behavior (Regression Prevention)

3.1 WHEN the user asks a genuine search query (e.g. "what is the weather today", "latest news about the election", "今日の天気は") THEN the system SHALL CONTINUE TO classify the input as `SEARCH` intent and trigger the web search pipeline

3.2 WHEN the user asks a building navigation question (e.g. "where is the cafeteria", "which floor is the gym on", "トイレはどこですか") THEN the system SHALL CONTINUE TO classify the input as `BUILDING` intent and trigger RAG retrieval

3.3 WHEN the keyword stage matches building or search keywords with confidence ≥ 0.7 THEN the system SHALL CONTINUE TO return that classification without falling through to the embedding stage

3.4 WHEN the embedding stage is used for genuinely ambiguous queries (not greetings) THEN the system SHALL CONTINUE TO resolve them using cosine similarity against anchor embeddings

3.5 WHEN the conversation history contains prior building or search turns and the user sends a short follow-up THEN the system SHALL CONTINUE TO carry forward the intent from history via the history carry-over mechanism

3.6 WHEN the LLM-based classification approach is added as an additional tier THEN the system SHALL CONTINUE TO fall back gracefully to the existing keyword/embedding approach if the LLM call fails or times out

---

## Bug Condition (Formal Specification)

### Bug Condition Function

```pascal
FUNCTION isBugCondition(X)
  INPUT: X of type UserInput { text: string, language: string }
  OUTPUT: boolean

  // Returns true when the input is a conversational/greeting phrase
  // that should never trigger the SEARCH pipeline
  RETURN isGreeting(X.text) OR isConversationalAcknowledgement(X.text)

  WHERE isGreeting(t) :=
    t matches any of: { "こんにちは", "おはよう", "こんばんは", "やあ",
                        "hello", "hi", "hey", "good morning", "good evening",
                        "howdy", "greetings" } (case-insensitive, trimmed)
    OR t is a short phrase (≤ 3 words / ≤ 10 characters) with no keyword hits
       in _BUILDING_KEYWORDS or _SEARCH_KEYWORDS

  WHERE isConversationalAcknowledgement(t) :=
    t matches any of: { "thanks", "thank you", "okay", "ok", "sure", "yes", "no",
                        "ありがとう", "わかりました", "はい", "いいえ" }
END FUNCTION
```

### Fix Checking Property

```pascal
// Property: Fix Checking — greetings must be classified as GENERAL
FOR ALL X WHERE isBugCondition(X) DO
  result ← classify'(X.text)
  ASSERT result.intent = GENERAL
END FOR
```

### Preservation Property

```pascal
// Property: Preservation Checking — non-greeting inputs unchanged
FOR ALL X WHERE NOT isBugCondition(X) DO
  ASSERT classify(X.text).intent = classify'(X.text).intent
END FOR
```

**Key:**
- `classify` = original (unfixed) classifier
- `classify'` = fixed classifier
- `F` = original function, `F'` = fixed function
