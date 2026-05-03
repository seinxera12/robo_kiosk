# Implementation Plan

- [x] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** — Ambiguous Keywords Cause False BUILDING Classifications
  - **CRITICAL**: This test MUST FAIL on unfixed code — failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior — it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the false BUILDING classifications
  - Create `server/llm/test_building_keyword_precision.py` using pytest + hypothesis
  - Import `IntentClassifier`, `Intent` from `server/llm/intent_classifier`
  - Define the confirmed false-positive inputs as a list:
    ```python
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
    ```
  - Use `hypothesis.strategies.sampled_from(_FALSE_POSITIVE_INPUTS)` to generate inputs
  - Instantiate `IntentClassifier(embedder=None)` (keyword-only path)
  - Assert `classify(text).intent != Intent.BUILDING` for all sampled inputs
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS — counterexamples such as `classify("store my data").intent == BUILDING` confirm the bug
  - Document counterexamples found (e.g. `"store my data"` → BUILDING hits: `["store"]`)
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** — Correct Building/Search Behavior Unchanged
  - **IMPORTANT**: Follow observation-first methodology
  - **Observe on UNFIXED code** (keyword-only classifier, no embedder):
    - `classify("where is the cafeteria").intent == BUILDING` ✓
    - `classify("which floor is the gym on").intent == BUILDING` ✓
    - `classify("トイレはどこですか").intent == BUILDING` ✓
    - `classify("find the nearest toilet").intent == BUILDING` ✓
    - `classify("how do I get to the cafeteria").intent == BUILDING` ✓
    - `classify("what is the weather today").intent == SEARCH` ✓
    - `classify("latest news about the election").intent == SEARCH` ✓
  - Write property-based tests in `server/llm/test_building_keyword_precision.py` capturing these observed behaviors:
    - **Property 2a**: For all queries containing an unambiguous building keyword (e.g. `"cafeteria"`, `"toilet"`, `"gym"`, `"elevator"`, `"floor"`, `"lobby"`, `"conference"`, `"parking"`, `"clinic"`, `"where is"`, `"which floor"`, and Japanese equivalents), `classify(text).intent == BUILDING`
    - **Property 2b**: For all queries containing a search keyword (and no unambiguous building keyword), `classify(text).intent == SEARCH`
    - **Property 2c**: Specific named queries — `"where is the cafeteria"`, `"which floor is the gym on"`, `"トイレはどこですか"`, `"find the nearest toilet"`, `"how do I get to the cafeteria"` — all return `BUILDING`
    - **Property 2d**: Specific named queries — `"what is the weather today"`, `"latest news about the election"` — return `SEARCH`
  - Verify all preservation tests PASS on UNFIXED code before implementing the fix
  - **EXPECTED OUTCOME**: Tests PASS (confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

- [x] 3. Fix for ambiguous keywords causing false BUILDING classifications

  - [x] 3.1 Remove 17 ambiguous entries from `_BUILDING_KEYWORDS` in `server/llm/intent_classifier.py`
    - Remove the following single words: `"store"`, `"shop"`, `"bank"`, `"garden"`, `"coffee"`, `"restaurant"`, `"cafe"`, `"nearest"`, `"closest"`, `"located"`, `"reception"`, `"terrace"`, `"retail"`
    - Remove the following navigation phrases: `"on the"`, `"find the"`, `"how to get"`, `"how do i get"`
    - Verify the remaining entries are all unambiguous building terms
    - _Bug_Condition: isBugCondition(X) — query's only building hits are from the removed ambiguous keywords_
    - _Requirements: 2.1, 2.2_

  - [x] 3.2 Add `_BUILDING_CONTEXT_WORDS` string and `_BUILDING_CONTEXT_PATTERNS` list at module level
    - Add `_BUILDING_CONTEXT_WORDS` as a regex alternation string of unambiguous building context anchors (e.g. `"floor"`, `"level"`, `"building"`, `"lobby"`, `"cafeteria"`, `"toilet"`, `"gym"`, `"elevator"`, `"conference"`, `"parking"`, `"clinic"`, `"entrance"`, `"exit"`, `"atm"`, and Japanese equivalents)
    - Add `_BUILDING_CONTEXT_PATTERNS` as a list of 4 compiled `re.Pattern` objects:
      1. Ambiguous word followed (within 30 chars) by a building context word
      2. Building context word followed (within 30 chars) by an ambiguous word
      3. `nearest`/`closest`/`located` followed (within 20 chars) by an unambiguous facility word
      4. `find the`/`how to get`/`how do i get` followed (within 30 chars) by an unambiguous facility word
    - All patterns use `re.IGNORECASE`
    - _Expected_Behavior: patterns match "restaurant on floor 3", "find the nearest toilet", "how do I get to the cafeteria" but NOT "find the best restaurant in tokyo", "store my data"_
    - _Requirements: 2.3, 2.4_

  - [x] 3.3 Add `_building_context_match(text_lower)` method to `IntentClassifier`
    - Returns a list of match description strings (one per matched pattern, empty if none match)
    - Iterates over `_BUILDING_CONTEXT_PATTERNS`, calls `pattern.search(text_lower)` for each
    - Each match description includes the pattern index and the matched substring (truncated to 30 chars)
    - Returns an empty list when no patterns match
    - _Requirements: 2.3, 2.4_

  - [x] 3.4 Update `_keyword_classify` to merge context pattern hits into building score
    - After computing `building_hits = [kw for kw in _BUILDING_KEYWORDS if kw in text_lower]`, call `context_hits = self._building_context_match(text_lower)`
    - Combine: `building_hits = building_hits + context_hits`
    - The rest of the scoring logic (building_score, search_score, confidence calculation) remains unchanged
    - _Preservation: unambiguous keyword hits still count; context pattern hits add to the score; search scoring is unaffected_
    - _Requirements: 2.3, 2.4, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [x] 3.5 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** — False Positives No Longer Classified as BUILDING
    - **IMPORTANT**: Re-run the SAME test from task 1 — do NOT write a new test
    - Run bug condition exploration test from step 1 against the fixed code
    - **EXPECTED OUTCOME**: Test PASSES — confirms `"store my data"`, `"shop online"`, `"bank account"`, `"on the topic of climate change"`, etc. no longer return `BUILDING`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [x] 3.6 Verify preservation tests still pass
    - **Property 2: Preservation** — Correct Building/Search Behavior Unchanged
    - **IMPORTANT**: Re-run the SAME tests from task 2 — do NOT write new tests
    - Run all preservation property tests from step 2 against the fixed code
    - **EXPECTED OUTCOME**: Tests PASS — confirms `"where is the cafeteria"`, `"which floor is the gym on"`, `"トイレはどこですか"`, `"find the nearest toilet"`, `"how do I get to the cafeteria"` still return `BUILDING`, and search queries still return `SEARCH`
    - Confirm no regressions introduced
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

- [x] 4. Checkpoint — Ensure all tests pass
  - Run the full test suite: `pytest server/llm/test_building_keyword_precision.py -v`
  - Ensure Property 1 (Bug Condition) test passes — all confirmed false positives no longer return `BUILDING`
  - Ensure Property 2 (Preservation) tests pass — all unambiguous building queries still return `BUILDING`, all search queries still return `SEARCH`
  - Ensure context pattern rescue works: `"find the nearest toilet"` and `"how do I get to the cafeteria"` still return `BUILDING`
  - Ensure `_building_context_match` returns empty list for `"store my data"`, `"find the best restaurant in tokyo"`, `"shop online"`
  - Ensure `_building_context_match` returns non-empty list for `"restaurant on floor 3"`, `"find the nearest toilet"`
  - Run the existing test suite to confirm no regressions: `pytest server/llm/test_intent_classifier.py -v`
