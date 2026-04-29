# Bugfix Requirements Document

## Introduction

The intent classifier in `server/llm/intent_classifier.py` incorrectly classifies non-building queries as `BUILDING` intent due to overly broad single words and generic phrases in the `_BUILDING_KEYWORDS` set. Words like `"store"`, `"shop"`, `"bank"`, `"garden"`, `"coffee"`, `"restaurant"`, `"cafe"`, `"nearest"`, `"closest"`, `"located"`, `"reception"`, `"terrace"`, and `"retail"` have common non-building meanings and appear frequently in everyday queries. Navigation phrases like `"on the"`, `"find the"`, `"how to get"`, and `"how do i get"` are so generic they match almost any sentence.

**Confirmed false positives:**
- `"on the topic of climate change"` → BUILDING (hits: `"on the"`)
- `"located in new york"` → BUILDING (hits: `"located"`)
- `"nearest hospital"` → BUILDING (hits: `"nearest"`)
- `"closest airport"` → BUILDING (hits: `"closest"`)
- `"store my data"` → BUILDING (hits: `"store"`)
- `"shop online"` → BUILDING (hits: `"shop"`)
- `"bank account"` → BUILDING (hits: `"bank"`)
- `"coffee shop near me"` → BUILDING (hits: `"shop"`, `"coffee"`)
- `"garden party ideas"` → BUILDING (hits: `"garden"`)
- `"find the best restaurant in tokyo"` → BUILDING (hits: `"restaurant"`, `"find the"`)

The fix removes the ambiguous keywords from `_BUILDING_KEYWORDS` and replaces them with context-requiring regex patterns (`_BUILDING_CONTEXT_PATTERNS`) that only match when the ambiguous word appears alongside a building/location context word.

---

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN a query contains the word `"store"`, `"shop"`, `"bank"`, `"garden"`, `"coffee"`, `"restaurant"`, `"cafe"`, `"nearest"`, `"closest"`, `"located"`, `"reception"`, `"terrace"`, or `"retail"` in a non-building context THEN the system classifies the query as `BUILDING` intent

1.2 WHEN a query contains the phrase `"on the"`, `"find the"`, `"how to get"`, or `"how do i get"` without any building-specific context THEN the system classifies the query as `BUILDING` intent

1.3 WHEN a query such as `"store my data"`, `"shop online"`, `"bank account"`, `"garden party ideas"`, or `"coffee shop near me"` is submitted THEN the system triggers building navigation RAG retrieval instead of routing to the correct intent

1.4 WHEN a query such as `"on the topic of climate change"` or `"located in new york"` is submitted THEN the system classifies it as `BUILDING` due to substring matches on `"on the"` and `"located"` respectively

1.5 WHEN a query such as `"nearest hospital"` or `"closest airport"` is submitted THEN the system classifies it as `BUILDING` because `"nearest"` and `"closest"` are in `_BUILDING_KEYWORDS`, even though the target is not a building facility

### Expected Behavior (Correct)

2.1 WHEN a query contains `"store"`, `"shop"`, `"bank"`, `"garden"`, `"coffee"`, `"restaurant"`, `"cafe"`, `"nearest"`, `"closest"`, `"located"`, `"reception"`, `"terrace"`, or `"retail"` WITHOUT an accompanying building/location context word THEN the system SHALL NOT classify the query as `BUILDING` intent based on that word alone

2.2 WHEN a query contains `"on the"`, `"find the"`, `"how to get"`, or `"how do i get"` WITHOUT an accompanying unambiguous building facility word THEN the system SHALL NOT classify the query as `BUILDING` intent based on that phrase alone

2.3 WHEN a query contains an ambiguous word (e.g. `"restaurant"`) alongside a building context word (e.g. `"floor"`, `"level"`, `"building"`, `"here"`, `"this"`) THEN the system SHALL classify the query as `BUILDING` intent

2.4 WHEN a query contains `"find the"` or `"how do i get"` followed by an unambiguous building facility word (e.g. `"cafeteria"`, `"toilet"`, `"gym"`) THEN the system SHALL classify the query as `BUILDING` intent

2.5 WHEN a query such as `"store my data"`, `"shop online"`, `"bank account"`, `"garden party ideas"`, or `"find the best restaurant in tokyo"` is submitted THEN the system SHALL route to `SEARCH` or `GENERAL` intent, not `BUILDING`

### Unchanged Behavior (Regression Prevention)

3.1 WHEN a query contains an unambiguous building facility word such as `"cafeteria"`, `"toilet"`, `"restroom"`, `"gym"`, `"elevator"`, `"lobby"`, `"conference"`, `"parking"`, `"clinic"`, `"auditorium"`, or their Japanese equivalents THEN the system SHALL CONTINUE TO classify the query as `BUILDING` intent

3.2 WHEN a query is `"where is the cafeteria"` THEN the system SHALL CONTINUE TO classify it as `BUILDING` intent

3.3 WHEN a query is `"which floor is the gym on"` THEN the system SHALL CONTINUE TO classify it as `BUILDING` intent

3.4 WHEN a query is `"トイレはどこですか"` THEN the system SHALL CONTINUE TO classify it as `BUILDING` intent

3.5 WHEN a query is `"find the nearest toilet"` THEN the system SHALL CONTINUE TO classify it as `BUILDING` intent (because `"toilet"` is unambiguous)

3.6 WHEN a query is `"how do I get to the cafeteria"` THEN the system SHALL CONTINUE TO classify it as `BUILDING` intent (because `"cafeteria"` is unambiguous)

3.7 WHEN a query is `"what is the weather today"` THEN the system SHALL CONTINUE TO classify it as `SEARCH` intent

3.8 WHEN a query is `"latest news about the election"` THEN the system SHALL CONTINUE TO classify it as `SEARCH` intent

---

## Bug Condition (Formal Specification)

### Bug Condition Function

```pascal
FUNCTION isBugCondition(X)
  INPUT: X of type UserInput { text: string }
  OUTPUT: boolean

  text_lower ← X.text.lower().strip()

  // Returns true when the query contains an ambiguous keyword that
  // appears WITHOUT a building context word, causing a false BUILDING hit
  ambiguousKeywords ← {
    "store", "shop", "bank", "garden", "coffee", "restaurant", "cafe",
    "nearest", "closest", "located", "reception", "terrace", "retail",
    "on the", "find the", "how to get", "how do i get"
  }

  unambiguousKeywords ← _BUILDING_KEYWORDS \ ambiguousKeywords
    // e.g. "cafeteria", "toilet", "gym", "elevator", "floor", "lobby", ...

  hasAmbiguousHit ← any(kw IN text_lower for kw in ambiguousKeywords)
  hasUnambiguousHit ← any(kw IN text_lower for kw in unambiguousKeywords)

  // Bug fires when the ONLY building keyword hits are ambiguous ones
  RETURN hasAmbiguousHit AND NOT hasUnambiguousHit
END FUNCTION
```

### Fix Checking Property

```pascal
// Property: Fix Checking — ambiguous-only queries must NOT be classified as BUILDING
FOR ALL X WHERE isBugCondition(X) DO
  result ← classify'(X.text)
  ASSERT result.intent ≠ BUILDING
    OR result was produced by _building_context_match(X.text)
END FOR
```

### Preservation Property

```pascal
// Property: Preservation Checking — non-buggy inputs unchanged
FOR ALL X WHERE NOT isBugCondition(X) DO
  ASSERT classify(X.text).intent = classify'(X.text).intent
END FOR
```

**Key:**
- `classify` = original (unfixed) classifier
- `classify'` = fixed classifier
- `F` = original function, `F'` = fixed function
