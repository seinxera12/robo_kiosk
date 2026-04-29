# Building Keyword Precision — Bugfix Design

## Overview

The intent classifier in `server/llm/intent_classifier.py` uses a keyword-matching Tier 1
that counts substring hits from `_BUILDING_KEYWORDS` against the lowercased query. The set
currently contains 17 entries that are too broad: single words with common non-building
meanings (`"store"`, `"shop"`, `"bank"`, `"garden"`, `"coffee"`, `"restaurant"`, `"cafe"`,
`"nearest"`, `"closest"`, `"located"`, `"reception"`, `"terrace"`, `"retail"`) and
navigation phrases so generic they match almost any sentence (`"on the"`, `"find the"`,
`"how to get"`, `"how do i get"`).

Because `_keyword_classify` counts raw substring hits, a single ambiguous match is enough
to push the building score above zero. When no search keywords are present, even one
building hit wins the tie-break (the classifier has a slight BUILDING preference on ties),
producing a false `BUILDING` classification.

The fix removes the 17 ambiguous entries from `_BUILDING_KEYWORDS` and replaces them with
a new `_BUILDING_CONTEXT_PATTERNS` list of compiled regex patterns. Each pattern requires
the ambiguous word to appear alongside a building/location context word before it counts as
a building signal. A new `_building_context_match(text_lower)` method checks these patterns,
and `_keyword_classify` is updated to include context-pattern hits in the building score.

---

## Glossary

- **Ambiguous keyword**: A word in `_BUILDING_KEYWORDS` that has common non-building
  meanings and causes false positives (e.g. `"store"`, `"shop"`, `"bank"`).
- **Unambiguous keyword**: A word in `_BUILDING_KEYWORDS` that is specific enough to
  reliably indicate a building query (e.g. `"cafeteria"`, `"toilet"`, `"elevator"`).
- **Context pattern**: A regex in `_BUILDING_CONTEXT_PATTERNS` that matches an ambiguous
  word only when it appears alongside a building context word.
- **Building context word**: A word that anchors an ambiguous term to a building meaning
  (e.g. `"floor"`, `"level"`, `"building"`, `"here"`, `"this"`, `"cafeteria"`).
- **`isBugCondition(X)`**: Pseudocode predicate — returns `true` when the query's only
  building keyword hits are ambiguous ones (no unambiguous keyword hit present).
- **`classify`** / **`F`**: The original (unfixed) classifier.
- **`classify'`** / **`F'`**: The fixed classifier.

---

## Bug Details

### Bug Condition

The bug fires when a query contains at least one ambiguous keyword from `_BUILDING_KEYWORDS`
and no unambiguous building keyword. The ambiguous hit is enough to give the building score
a non-zero value. If the search score is also zero (or lower), `_keyword_classify` returns
`BUILDING` with confidence ≥ 0.7, short-circuiting the embedding tier.

```
FUNCTION isBugCondition(X)
  INPUT:  X of type UserInput { text: string }
  OUTPUT: boolean

  text_lower ← X.text.lower().strip()

  ambiguousKeywords ← {
    "store", "shop", "bank", "garden", "coffee", "restaurant", "cafe",
    "nearest", "closest", "located", "reception", "terrace", "retail",
    "on the", "find the", "how to get", "how do i get"
  }

  unambiguousKeywords ← _BUILDING_KEYWORDS \ ambiguousKeywords

  hasAmbiguousHit    ← any(kw IN text_lower for kw in ambiguousKeywords)
  hasUnambiguousHit  ← any(kw IN text_lower for kw in unambiguousKeywords)

  RETURN hasAmbiguousHit AND NOT hasUnambiguousHit
END FUNCTION
```

### Confirmed False Positives

| Query | Ambiguous hit(s) | Expected intent |
|---|---|---|
| `"on the topic of climate change"` | `"on the"` | GENERAL / SEARCH |
| `"located in new york"` | `"located"` | SEARCH / GENERAL |
| `"nearest hospital"` | `"nearest"` | SEARCH / GENERAL |
| `"closest airport"` | `"closest"` | SEARCH / GENERAL |
| `"store my data"` | `"store"` | GENERAL |
| `"shop online"` | `"shop"` | GENERAL |
| `"bank account"` | `"bank"` | GENERAL |
| `"coffee shop near me"` | `"shop"`, `"coffee"` | SEARCH / GENERAL |
| `"garden party ideas"` | `"garden"` | GENERAL |
| `"find the best restaurant in tokyo"` | `"restaurant"`, `"find the"` | SEARCH |

### Preserved Correct Behaviors

| Query | Unambiguous hit(s) | Expected intent |
|---|---|---|
| `"where is the cafeteria"` | `"cafeteria"`, `"where is"` | BUILDING ✓ |
| `"which floor is the gym on"` | `"floor"`, `"gym"`, `"which floor"` | BUILDING ✓ |
| `"トイレはどこですか"` | `"トイレ"`, `"どこ"` | BUILDING ✓ |
| `"find the nearest toilet"` | `"toilet"` | BUILDING ✓ |
| `"how do I get to the cafeteria"` | `"cafeteria"` | BUILDING ✓ |
| `"what is the weather today"` | (search keywords) | SEARCH ✓ |
| `"latest news about the election"` | (search keywords) | SEARCH ✓ |

---

## Expected Behavior

### Preservation Requirements

All inputs that do NOT satisfy `isBugCondition(X)` must produce the same intent after the
fix. This includes:

- Queries containing unambiguous building keywords (`"cafeteria"`, `"toilet"`, `"gym"`,
  `"elevator"`, `"lobby"`, `"conference"`, `"parking"`, `"clinic"`, etc.) — must remain
  `BUILDING`.
- Queries containing search keywords — must remain `SEARCH`.
- Queries where an ambiguous word appears alongside a building context word (matched by a
  context pattern) — must remain `BUILDING`.
- Queries resolved by the history carry-over mechanism — must remain unchanged.
- The keyword short-circuit at confidence ≥ 0.7 must continue to bypass the embedding tier.

---

## Correctness Properties

**Property 1: Fix Checking — Ambiguous-Only Queries Not Classified as BUILDING**

For any input `X` where `isBugCondition(X)` returns `true` (the query's only building
keyword hits are ambiguous ones, and no context pattern matches), the fixed `classify'`
function SHALL NOT return `intent = BUILDING`.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**

---

**Property 2: Preservation — Unambiguous Building Queries Unchanged**

For any input `X` containing at least one unambiguous building keyword (e.g. `"cafeteria"`,
`"toilet"`, `"gym"`, `"elevator"`, `"floor"`, `"lobby"`, `"conference"`, `"parking"`,
`"clinic"`, `"auditorium"`, `"where is"`, `"which floor"`, `"what floor"`, and their
Japanese equivalents), the fixed `classify'` function SHALL return `intent = BUILDING`.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**

---

**Property 3: Preservation — Search Queries Unchanged**

For any input `X` containing at least one `_SEARCH_KEYWORDS` entry, the fixed `classify'`
function SHALL return `intent = SEARCH` (assuming no building keywords also present).

**Validates: Requirements 3.7, 3.8**

---

**Property 4: Context Pattern Rescue — Ambiguous Word + Building Context = BUILDING**

For any input `X` where an ambiguous word appears alongside a building context word (matched
by a `_BUILDING_CONTEXT_PATTERNS` entry), the fixed `classify'` function SHALL return
`intent = BUILDING`.

**Validates: Requirements 2.3, 2.4**

---

## Fix Implementation

### Changes Required

**File:** `server/llm/intent_classifier.py`

---

### Change 1 — Remove ambiguous entries from `_BUILDING_KEYWORDS`

Remove the following 17 entries from `_BUILDING_KEYWORDS`:

```python
# Remove these ambiguous single words:
"store", "shop", "bank", "garden", "coffee", "restaurant", "cafe",
"nearest", "closest", "located", "reception", "terrace", "retail",

# Remove these overly broad navigation phrases:
"on the", "find the", "how to get", "how do i get",
```

The remaining entries in `_BUILDING_KEYWORDS` are all unambiguous building terms
(e.g. `"cafeteria"`, `"toilet"`, `"elevator"`, `"floor"`, `"lobby"`, `"gym"`,
`"conference"`, `"parking"`, `"clinic"`, `"where is"`, `"which floor"`, and all Japanese
equivalents).

---

### Change 2 — Add `_BUILDING_CONTEXT_PATTERNS` list

Add a new module-level list of compiled regex patterns. Each pattern matches an ambiguous
word only when it appears alongside a building/location context word.

```python
# Building context words used as anchors in patterns
_BUILDING_CONTEXT_WORDS = (
    r"floor|level|building|here|this|lobby|office|room|wing|block|site|"
    r"cafeteria|canteen|toilet|restroom|bathroom|washroom|gym|fitness|"
    r"clinic|pharmacy|conference|meeting|parking|elevator|lift|stairs|"
    r"entrance|exit|rooftop|auditorium|atm|階|フロア|部屋|建物|ここ|この"
)

_BUILDING_CONTEXT_PATTERNS: list[re.Pattern] = [
    # "restaurant on floor 3", "restaurant in this building", "restaurant here"
    re.compile(
        r"\b(?:restaurant|cafe|coffee|shop|store|bank|garden|terrace|retail|reception)\b"
        r".{0,30}"
        r"\b(?:" + _BUILDING_CONTEXT_WORDS + r")\b",
        re.IGNORECASE,
    ),
    # "floor 2 restaurant", "building cafe", "this shop"
    re.compile(
        r"\b(?:" + _BUILDING_CONTEXT_WORDS + r")\b"
        r".{0,30}"
        r"\b(?:restaurant|cafe|coffee|shop|store|bank|garden|terrace|retail|reception)\b",
        re.IGNORECASE,
    ),
    # "nearest toilet", "closest restroom" — nearest/closest + unambiguous facility
    re.compile(
        r"\b(?:nearest|closest|located)\b"
        r".{0,20}"
        r"\b(?:toilet|restroom|bathroom|washroom|cafeteria|canteen|gym|fitness|"
        r"clinic|pharmacy|conference|meeting|parking|elevator|lift|stairs|"
        r"entrance|exit|lobby|atm|トイレ|お手洗い|化粧室|カフェテリア|ジム)\b",
        re.IGNORECASE,
    ),
    # "find the cafeteria", "find the toilet" — find the + unambiguous facility
    re.compile(
        r"\b(?:find the|how to get|how do i get)\b"
        r".{0,30}"
        r"\b(?:toilet|restroom|bathroom|washroom|cafeteria|canteen|gym|fitness|"
        r"clinic|pharmacy|conference|meeting|parking|elevator|lift|stairs|"
        r"entrance|exit|lobby|atm|トイレ|お手洗い|化粧室|カフェテリア|ジム)\b",
        re.IGNORECASE,
    ),
]
```

---

### Change 3 — Add `_building_context_match(text_lower)` method

Add a helper method to `IntentClassifier` that checks the context patterns:

```python
def _building_context_match(self, text_lower: str) -> list[str]:
    """
    Returns a list of matched context pattern descriptions for text_lower.
    Returns an empty list if no context patterns match.
    Used by _keyword_classify to rescue ambiguous words in building context.
    """
    matched = []
    for i, pattern in enumerate(_BUILDING_CONTEXT_PATTERNS):
        m = pattern.search(text_lower)
        if m:
            matched.append(f"context_pattern_{i}:{m.group(0)[:30]}")
    return matched
```

---

### Change 4 — Update `_keyword_classify` to use context patterns

In `_keyword_classify`, after computing `building_hits`, add context pattern hits to the
building score:

```python
def _keyword_classify(self, text_lower: str) -> ClassificationResult:
    # ... existing override phrase check ...

    building_hits = [kw for kw in _BUILDING_KEYWORDS if kw in text_lower]
    search_hits   = [kw for kw in _SEARCH_KEYWORDS   if kw in text_lower]

    # NEW: add context pattern hits to building score
    context_hits = self._building_context_match(text_lower)
    building_hits = building_hits + context_hits   # combine for scoring

    building_score = len(building_hits)
    search_score   = len(search_hits)

    # ... rest of scoring logic unchanged ...
```

---

### Specific Changes Summary

1. **Remove 17 ambiguous entries** from `_BUILDING_KEYWORDS` (the 13 single words + 4
   navigation phrases listed above).
2. **Add `_BUILDING_CONTEXT_WORDS` string** at module level (reused across patterns).
3. **Add `_BUILDING_CONTEXT_PATTERNS` list** at module level with 4 compiled regex patterns.
4. **Add `_building_context_match(text_lower)` method** to `IntentClassifier`.
5. **Update `_keyword_classify`** to merge context pattern hits into `building_hits` before
   scoring.

---

## Testing Strategy

### Validation Approach

Two-phase approach: first write a bug condition exploration test that FAILS on unfixed code
(confirming the false positives exist), then write preservation tests that PASS on unfixed
code (capturing correct baseline behavior). After implementing the fix, both sets must pass.

---

### Exploratory Bug Condition Checking

**Goal:** Confirm the false positives exist on unfixed code before implementing the fix.

**Test Cases (all expected to produce BUILDING on unfixed code):**

1. `"on the topic of climate change"` → expect NOT BUILDING, observe BUILDING (fail)
2. `"located in new york"` → expect NOT BUILDING, observe BUILDING (fail)
3. `"nearest hospital"` → expect NOT BUILDING, observe BUILDING (fail)
4. `"closest airport"` → expect NOT BUILDING, observe BUILDING (fail)
5. `"store my data"` → expect NOT BUILDING, observe BUILDING (fail)
6. `"shop online"` → expect NOT BUILDING, observe BUILDING (fail)
7. `"bank account"` → expect NOT BUILDING, observe BUILDING (fail)
8. `"coffee shop near me"` → expect NOT BUILDING, observe BUILDING (fail)
9. `"garden party ideas"` → expect NOT BUILDING, observe BUILDING (fail)
10. `"find the best restaurant in tokyo"` → expect NOT BUILDING, observe BUILDING (fail)

**Property (pseudocode):**

```pascal
FOR ALL X WHERE isBugCondition(X) DO
  result ← classify(X.text)   // unfixed
  ASSERT result.intent = BUILDING   // confirms bug
END FOR
```

---

### Fix Checking

**Goal:** Verify that after the fix, all confirmed false positives are no longer classified
as BUILDING.

**Property (pseudocode):**

```pascal
FOR ALL X WHERE isBugCondition(X) DO
  result ← classify'(X.text)   // fixed
  ASSERT result.intent ≠ BUILDING
END FOR
```

---

### Preservation Checking

**Goal:** Verify that unambiguous building queries, search queries, and context-pattern
rescues all produce the correct intent after the fix.

**Property 2 (pseudocode):**

```pascal
// Unambiguous building queries must remain BUILDING
FOR ALL X WHERE hasUnambiguousKeyword(X) DO
  ASSERT classify'(X.text).intent = BUILDING
END FOR

// Search queries must remain SEARCH
FOR ALL X WHERE hasSearchKeyword(X) AND NOT hasUnambiguousKeyword(X) DO
  ASSERT classify'(X.text).intent = SEARCH
END FOR

// Context pattern rescues must produce BUILDING
FOR ALL X WHERE contextPatternMatches(X) DO
  ASSERT classify'(X.text).intent = BUILDING
END FOR
```

---

### Unit Tests

- Test that each of the 17 removed keywords no longer appears in `_BUILDING_KEYWORDS`.
- Test `_building_context_match("restaurant on floor 3")` returns a non-empty list.
- Test `_building_context_match("find the nearest toilet")` returns a non-empty list.
- Test `_building_context_match("find the best restaurant in tokyo")` returns an empty list.
- Test `_building_context_match("store my data")` returns an empty list.
- Test `classify("where is the cafeteria").intent == BUILDING` (unambiguous keyword).
- Test `classify("which floor is the gym on").intent == BUILDING`.
- Test `classify("トイレはどこですか").intent == BUILDING`.
- Test `classify("find the nearest toilet").intent == BUILDING` (context pattern rescue).
- Test `classify("how do I get to the cafeteria").intent == BUILDING` (unambiguous keyword).
- Test `classify("store my data").intent != BUILDING`.
- Test `classify("shop online").intent != BUILDING`.
- Test `classify("bank account").intent != BUILDING`.
- Test `classify("on the topic of climate change").intent != BUILDING`.
- Test `classify("what is the weather today").intent == SEARCH`.
- Test `classify("latest news about the election").intent == SEARCH`.

### Property-Based Tests

- **Property 1 (Fix Checking)**: For all confirmed false-positive queries, assert
  `classify'(X).intent != BUILDING`.
- **Property 2a (Preservation — unambiguous building)**: For all queries containing an
  unambiguous building keyword, assert `classify'(X).intent == BUILDING`.
- **Property 2b (Preservation — search)**: For all queries containing a search keyword
  (and no unambiguous building keyword), assert `classify'(X).intent == SEARCH`.
- **Property 2c (Preservation — context rescue)**: For all queries where an ambiguous word
  appears alongside a building context word, assert `classify'(X).intent == BUILDING`.
