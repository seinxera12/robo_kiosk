# CosyVoice English Language Output Bugfix Design

## Overview

The CosyVoice TTS service incorrectly generates Chinese audio when processing English text input. The bug occurs because the service uses `inference_zero_shot()` method with a Chinese-language prompt file, causing the model to default to Chinese synthesis regardless of input language. The fix requires switching to `inference_cross_lingual()` method with proper English language tagging (`<|en|>`) and using the appropriate cross-lingual prompt file.

## Glossary

- **Bug_Condition (C)**: The condition that triggers the bug - when English text is processed but generates Chinese audio output
- **Property (P)**: The desired behavior when English text is provided - the system should generate English audio output
- **Preservation**: Existing audio format, error handling, and model initialization behavior that must remain unchanged by the fix
- **inference_zero_shot()**: The current method in `app.py` that causes Chinese audio generation for English text
- **inference_cross_lingual()**: The correct method that supports language-specific synthesis with language tags
- **Language Tag**: The `<|en|>` prefix that specifies English language for cross-lingual synthesis

## Bug Details

### Bug Condition

The bug manifests when English text is provided to the `/synthesize` endpoint but the system generates audio in Chinese language instead of English. The `synthesize()` function in `app.py` is using the wrong inference method (`inference_zero_shot`) with a Chinese-language prompt file, causing the model to default to Chinese synthesis characteristics regardless of the input text language.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type SynthesisRequest
  OUTPUT: boolean
  
  RETURN input.text IS_ENGLISH_TEXT
         AND synthesize_method == "inference_zero_shot"
         AND prompt_file == "zero_shot_prompt.wav"
         AND generated_audio_language == "Chinese"
END FUNCTION
```

### Examples

- **Input**: "Hello, how are you today?" → **Actual**: Chinese audio output → **Expected**: English audio output
- **Input**: "The weather is nice today." → **Actual**: Chinese audio output → **Expected**: English audio output  
- **Input**: "Thank you for your help." → **Actual**: Chinese audio output → **Expected**: English audio output
- **Edge Case**: Empty or whitespace-only English text → **Expected**: HTTP 400 error (preserved behavior)

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- WAV audio format output with 22050 Hz sample rate must continue to work exactly as before
- Audio conversion to int16 PCM format must remain unchanged
- HTTP error responses for invalid inputs must continue to work as before
- Model initialization and loading process must remain unchanged
- Health check and speaker listing endpoints must continue to work as before

**Scope:**
All inputs and behaviors that do NOT involve the specific synthesis method and prompt file selection should be completely unaffected by this fix. This includes:
- Audio format conversion and output generation
- Error handling for empty text, model loading failures, and synthesis errors
- API endpoint responses and status codes
- Model initialization and device configuration

## Hypothesized Root Cause

Based on the bug description and code analysis, the most likely issues are:

1. **Incorrect Inference Method**: The service uses `inference_zero_shot()` which doesn't support language specification
   - Zero-shot method relies on prompt characteristics to determine output language
   - The `zero_shot_prompt.wav` file contains Chinese language characteristics

2. **Missing Language Tag**: The text input lacks the `<|en|>` language tag prefix required for English synthesis
   - Cross-lingual method requires explicit language specification
   - Without the tag, the model defaults to the prompt file's language characteristics

3. **Wrong Prompt File**: Using `zero_shot_prompt.wav` instead of `cross_lingual_prompt.wav`
   - Zero-shot prompt is optimized for Chinese language synthesis
   - Cross-lingual prompt is designed for multi-language synthesis including English

4. **Incorrect Prompt Text**: The hardcoded prompt text "Hello, this is a natural English voice." may not be optimal for cross-lingual synthesis

## Correctness Properties

Property 1: Bug Condition - English Text Generates English Audio

_For any_ English text input provided to the `/synthesize` endpoint, the fixed function SHALL generate audio output in English language that matches the linguistic characteristics and pronunciation of the input text.

**Validates: Requirements 2.1, 2.2, 2.3**

Property 2: Preservation - Audio Format and Error Handling

_For any_ synthesis request (regardless of language), the fixed function SHALL produce the same WAV audio format (22050 Hz, int16 PCM), error handling behavior, and API response structure as the original function, preserving all existing non-language-specific functionality.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `cosyvoice_service/app.py`

**Function**: `synthesize()`

**Specific Changes**:
1. **Replace Inference Method**: Change from `inference_zero_shot()` to `inference_cross_lingual()`
   - Remove the `prompt_text` parameter (not used in cross-lingual method)
   - Add `<|en|>` language tag prefix to the input text

2. **Update Prompt File Path**: Change from `zero_shot_prompt.wav` to `cross_lingual_prompt.wav`
   - Update the file path construction to use the correct prompt file
   - Ensure the cross-lingual prompt file exists in the asset directory

3. **Modify Text Processing**: Add language tag prefix to English text input
   - Prepend `<|en|>` to the request.text before passing to inference method
   - Maintain original text validation and error handling

4. **Update Method Call**: Adjust the inference method call signature
   - Remove prompt_text parameter
   - Keep the prompt_wav_path parameter with updated file path
   - Maintain stream=False parameter

5. **Preserve Audio Processing**: Keep all existing audio conversion and response logic unchanged
   - Maintain the same audio extraction from generator
   - Keep the same WAV conversion and HTTP response format

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bug on unfixed code, then verify the fix works correctly and preserves existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm or refute the root cause analysis. If we refute, we will need to re-hypothesize.

**Test Plan**: Write tests that send English text to the `/synthesize` endpoint and analyze the generated audio language characteristics. Run these tests on the UNFIXED code to observe Chinese audio generation and understand the root cause.

**Test Cases**:
1. **Simple English Text**: Send "Hello world" and verify audio is in Chinese (will fail on unfixed code)
2. **Complex English Sentence**: Send "The quick brown fox jumps over the lazy dog" and verify audio is in Chinese (will fail on unfixed code)
3. **English with Numbers**: Send "I have 5 apples and 3 oranges" and verify audio is in Chinese (will fail on unfixed code)
4. **Long English Text**: Send a paragraph of English text and verify audio is in Chinese (will fail on unfixed code)

**Expected Counterexamples**:
- Generated audio will have Chinese pronunciation characteristics for English words
- Possible causes: wrong inference method, missing language tag, incorrect prompt file

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed function produces the expected behavior.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := synthesize_fixed(input)
  ASSERT expectedBehavior(result)
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed function produces the same result as the original function.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT synthesize_original(input) = synthesize_fixed(input)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many test cases automatically across the input domain
- It catches edge cases that manual unit tests might miss
- It provides strong guarantees that behavior is unchanged for all non-buggy inputs

**Test Plan**: Observe behavior on UNFIXED code first for audio format, error handling, and API responses, then write property-based tests capturing that behavior.

**Test Cases**:
1. **Audio Format Preservation**: Observe that WAV format with 22050 Hz works correctly on unfixed code, then verify this continues after fix
2. **Error Handling Preservation**: Observe that empty text returns HTTP 400 on unfixed code, then verify this continues after fix
3. **Model Loading Preservation**: Observe that model initialization works correctly on unfixed code, then verify this continues after fix
4. **API Response Preservation**: Observe that response headers and content-type work correctly on unfixed code, then verify this continues after fix

### Unit Tests

- Test English text synthesis with cross-lingual method produces English audio
- Test that language tag prefix is correctly added to input text
- Test that cross-lingual prompt file is used instead of zero-shot prompt
- Test edge cases (empty text, very long text, special characters)

### Property-Based Tests

- Generate random English text inputs and verify they produce English audio output
- Generate random synthesis parameters and verify audio format preservation
- Test that all error conditions continue to work across many scenarios

### Integration Tests

- Test full API flow with English text input and verify English audio output
- Test that health check and speaker endpoints continue to work after fix
- Test that model loading and initialization process remains unchanged