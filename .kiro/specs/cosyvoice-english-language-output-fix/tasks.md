# Implementation Plan

- [ ] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - English Text Generates Chinese Audio
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the bug exists
  - **Scoped PBT Approach**: For deterministic bugs, scope the property to the concrete failing case(s) to ensure reproducibility
  - Test that English text input to `/synthesize` endpoint generates Chinese audio output (from Bug Condition in design)
  - Test cases: "Hello world", "The quick brown fox jumps over the lazy dog", "I have 5 apples and 3 oranges"
  - Verify audio language characteristics match Chinese pronunciation patterns
  - The test assertions should match the Expected Behavior Properties from design
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS (this is correct - it proves the bug exists)
  - Document counterexamples found to understand root cause
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 1.2, 1.3_

- [ ] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Audio Format and Error Handling
  - **IMPORTANT**: Follow observation-first methodology
  - Observe behavior on UNFIXED code for non-buggy inputs
  - Write property-based tests capturing observed behavior patterns from Preservation Requirements
  - Property-based testing generates many test cases for stronger guarantees
  - Test WAV audio format with 22050 Hz sample rate preservation
  - Test int16 PCM audio conversion preservation
  - Test HTTP error response preservation for invalid inputs
  - Test model initialization and loading preservation
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (this confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [ ] 3. Fix for English language output bug

  - [x] 3.1 Implement the fix
    - Replace `inference_zero_shot()` with `inference_cross_lingual()` method
    - Add `<|en|>` language tag prefix to English text input
    - Change prompt file from `zero_shot_prompt.wav` to `cross_lingual_prompt.wav`
    - Remove `prompt_text` parameter from inference method call
    - Maintain existing audio processing and response logic
    - _Bug_Condition: isBugCondition(input) where input.text IS_ENGLISH_TEXT AND synthesize_method == "inference_zero_shot" AND prompt_file == "zero_shot_prompt.wav" AND generated_audio_language == "Chinese"_
    - _Expected_Behavior: expectedBehavior(result) - English text generates English audio output with cross-lingual method_
    - _Preservation: Audio format (WAV, 22050 Hz, int16 PCM), error handling, model initialization unchanged_
    - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4_

  - [ ] 3.2 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - English Text Generates English Audio
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior
    - When this test passes, it confirms the expected behavior is satisfied
    - Run bug condition exploration test from step 1
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - _Requirements: 2.1, 2.2, 2.3_

  - [ ] 3.3 Verify preservation tests still pass
    - **Property 2: Preservation** - Audio Format and Error Handling
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run preservation property tests from step 2
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
    - Confirm all tests still pass after fix (no regressions)
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [ ] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.