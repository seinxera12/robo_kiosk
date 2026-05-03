# Implementation Plan

- [x] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - Conversational Inputs Misclassified as SEARCH
  - **CRITICAL**: This test MUST FAIL on unfixed code — failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior — it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the bug exists
  - **Scoped PBT Approach**: Scope the property to the concrete failing cases from `_CONVERSATIONAL_INPUTS` (greetings and acknowledgements) to ensure reproducibility
  - Create `server/llm/test_intent_classifier.py` using pytest + hypothesis
  - Import `IntentClassifier`, `Intent`, and `_CONVERSATIONAL_INPUTS` (once added) from `server/llm/intent_classifier`
  - For the unfixed code, use the known conversational inputs from the design: `{"こんにちは", "hello", "hi", "おはよう", "ありがとう", "okay", "やあ", "thanks", "good morning", "hey"}`
  - Use `hypothesis.strategies.sampled_from(conversational_inputs)` to generate inputs
  - Instantiate `IntentClassifier` without an embedder (keyword-only path) AND with a mock embedder that returns SEARCH-biased cosine similarities (simulating the real embedding bug)
  - For the mock embedder, return embeddings where SEARCH anchors score ~0.84 for any short input (reproducing the `こんにちは` → SEARCH 84.20% bug)
  - Assert `classify(text).intent == Intent.GENERAL` for all sampled conversational inputs
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS — counterexamples such as `classify("こんにちは").intent == SEARCH` (confidence ≈ 0.84) confirm the bug
  - Document counterexamples found (e.g. `"こんにちは"` → SEARCH, `"hello"` → SEARCH, `"okay"` → SEARCH)
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 1.2, 1.3_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Non-Conversational Input Behavior Unchanged
  - **IMPORTANT**: Follow observation-first methodology
  - **Observe on UNFIXED code** (keyword-only classifier, no embedder):
    - `classify("what is the weather today").intent == SEARCH` ✓
    - `classify("where is the cafeteria").intent == BUILDING` ✓
    - `classify("今日の天気は").intent == SEARCH` ✓
    - `classify("トイレはどこですか").intent == BUILDING` ✓
    - `classify("which floor is the gym on").intent == BUILDING` ✓
    - `classify("latest news about the election").intent == SEARCH` ✓
    - `classify("天気 今日").intent == SEARCH` ✓ (short phrase WITH keyword hit — must NOT be intercepted by Tier 0)
  - Write property-based tests in `server/llm/test_intent_classifier.py` capturing these observed behaviors:
    - **Property 2a**: For all inputs containing at least one `_SEARCH_KEYWORDS` entry, `classify(text).intent == SEARCH` (use `hypothesis.strategies` to build such strings)
    - **Property 2b**: For all inputs containing at least one `_BUILDING_KEYWORDS` entry, `classify(text).intent == BUILDING`
    - **Property 2c**: For all short phrases (≤ 3 words, ≤ 15 chars) that contain a keyword hit, the result is NOT intercepted by Tier 0 (i.e. `method != "conversational_guard"`)
    - **Property 2d**: Keyword short-circuit — inputs with ≥ 2 keyword hits return confidence ≥ 0.7 and bypass the embedding tier
  - Verify all preservation tests PASS on UNFIXED code before implementing the fix
  - **EXPECTED OUTCOME**: Tests PASS (confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 3. Fix for conversational inputs misclassified as SEARCH

  - [x] 3.1 Add `_CONVERSATIONAL_INPUTS` set at module level in `server/llm/intent_classifier.py`
    - Add alongside the existing `_BUILDING_KEYWORDS` and `_SEARCH_KEYWORDS` sets
    - Include all English greetings: `"hello"`, `"hi"`, `"hey"`, `"howdy"`, `"greetings"`, `"sup"`, `"yo"`, `"good morning"`, `"good afternoon"`, `"good evening"`, `"good night"`
    - Include all English acknowledgements: `"thanks"`, `"thank you"`, `"okay"`, `"ok"`, `"sure"`, `"yes"`, `"no"`, `"got it"`, `"understood"`, `"alright"`, `"cool"`, `"great"`, `"nice"`
    - Include all Japanese greetings: `"こんにちは"`, `"おはよう"`, `"おはようございます"`, `"こんばんは"`, `"やあ"`, `"どうも"`
    - Include all Japanese acknowledgements: `"ありがとう"`, `"ありがとうございます"`, `"わかりました"`, `"はい"`, `"いいえ"`, `"なるほど"`, `"そうですか"`, `"了解"`
    - _Bug_Condition: isBugCondition(X) where X.text.lower().strip() IN _CONVERSATIONAL_INPUTS OR (word_count ≤ 3 AND char_count ≤ 15 AND no keyword hits)_
    - _Requirements: 2.1, 2.2, 2.4_

  - [x] 3.2 Add `_is_conversational(text_lower)` helper method to `IntentClassifier`
    - Returns `True` if `text_lower` is in `_CONVERSATIONAL_INPUTS`
    - Also returns `True` if `word_count(text_lower) ≤ 3` AND `len(text_lower) ≤ 15` AND no `_BUILDING_KEYWORDS` hit AND no `_SEARCH_KEYWORDS` hit (catches unlisted greeting variants)
    - Returns `False` for all other inputs — including short phrases that DO contain a keyword hit
    - _Bug_Condition: isBugCondition(X) from design_
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 3.3 Insert Tier 0 guard at the top of `classify()`, before the `_keyword_classify` call
    - Add immediately after `text_lower = text.lower().strip()` and before the `# --- Tier 1: keyword rules ---` block
    - If `self._is_conversational(text_lower)` returns `True`, return `ClassificationResult(intent=Intent.GENERAL, confidence=0.95, method="conversational_guard", matched_keywords=[])`
    - Log at DEBUG level: `f"Intent (conversational guard): GENERAL for '{text_lower[:20]}'"`
    - _Expected_Behavior: classify'(X).intent = GENERAL, method = "conversational_guard" for all isBugCondition(X) inputs_
    - _Preservation: Tier 0 is only reached when _is_conversational returns True; all keyword-matched inputs bypass it_
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [x] 3.4 Extend `_GENERAL_ANCHORS` with short greeting-like phrases
    - Add to the existing `_GENERAL_ANCHORS` list: `"hello"`, `"hi there"`, `"good morning"`, `"thanks"`, `"okay"`, `"sure"`, `"こんにちは"`, `"ありがとう"`, `"はい"`
    - This strengthens the embedding tier as a secondary defense for greeting variants not in the explicit list
    - _Preservation: _GENERAL_ANCHORS additions only affect the embedding tier fallback; Tier 1 keyword behavior is unchanged_
    - _Requirements: 2.1, 2.4_

  - [x] 3.5 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Conversational Inputs Classified as GENERAL
    - **IMPORTANT**: Re-run the SAME test from task 1 — do NOT write a new test
    - The test from task 1 encodes the expected behavior: `classify(text).intent == GENERAL` for all conversational inputs
    - When this test passes, it confirms the Tier 0 guard correctly intercepts all `isBugCondition(X)` inputs
    - Run bug condition exploration test from step 1 against the fixed code
    - **EXPECTED OUTCOME**: Test PASSES — confirms `こんにちは`, `hello`, `okay`, `ありがとう`, etc. all return `GENERAL`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [x] 3.6 Verify preservation tests still pass
    - **Property 2: Preservation** - Non-Conversational Input Behavior Unchanged
    - **IMPORTANT**: Re-run the SAME tests from task 2 — do NOT write new tests
    - Run all preservation property tests from step 2 against the fixed code
    - **EXPECTED OUTCOME**: Tests PASS — confirms SEARCH/BUILDING routing is unaffected and Tier 0 does not intercept keyword-bearing inputs
    - Confirm all tests still pass after fix (no regressions)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 4. Checkpoint — Ensure all tests pass
  - Run the full test suite: `pytest server/llm/test_intent_classifier.py -v`
  - Ensure Property 1 (Bug Condition) test passes — all conversational inputs return `GENERAL`
  - Ensure Property 2 (Preservation) tests pass — all SEARCH/BUILDING/keyword-short-circuit behaviors unchanged
  - Ensure all unit tests for `_is_conversational()` pass (explicit list entries, short no-keyword phrases, short phrases WITH keywords)
  - Ensure `method == "conversational_guard"` for Tier 0 intercepts and `method != "conversational_guard"` for keyword-matched inputs
  - Ask the user if any questions arise about edge cases (e.g. `"ok google"` — contains no keywords but is 2 words; `"天気"` alone — 1 word but IS a search keyword)
