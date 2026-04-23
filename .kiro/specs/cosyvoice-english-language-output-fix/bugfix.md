# Bugfix Requirements Document

## Introduction

The CosyVoice TTS service is generating audio output in Chinese instead of English when processing English text input. This occurs because the current implementation uses the wrong inference method (`inference_zero_shot`) and lacks proper language specification for English synthesis. The bug affects all English text synthesis requests, making the service unusable for English TTS despite accepting English text input.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN English text is provided to the `/synthesize` endpoint THEN the system generates audio output in Chinese language instead of English

1.2 WHEN the service uses `inference_zero_shot()` method with English text THEN the system defaults to Chinese language synthesis without language specification

1.3 WHEN the service uses `zero_shot_prompt.wav` as the audio prompt THEN the system follows the Chinese language characteristics of that prompt file

### Expected Behavior (Correct)

2.1 WHEN English text is provided to the `/synthesize` endpoint THEN the system SHALL generate audio output in English language matching the input text

2.2 WHEN the service processes English text THEN the system SHALL use `inference_cross_lingual()` method with `<|en|>` language tag prefix

2.3 WHEN the service synthesizes English speech THEN the system SHALL use `cross_lingual_prompt.wav` as the appropriate audio prompt for cross-lingual synthesis

### Unchanged Behavior (Regression Prevention)

3.1 WHEN the service receives valid English text input THEN the system SHALL CONTINUE TO return WAV audio format with 22050 Hz sample rate

3.2 WHEN the service processes synthesis requests THEN the system SHALL CONTINUE TO handle audio conversion to int16 PCM format correctly

3.3 WHEN the service encounters synthesis errors THEN the system SHALL CONTINUE TO return appropriate HTTP error responses with detailed error messages

3.4 WHEN the service loads the CosyVoice2 model THEN the system SHALL CONTINUE TO initialize successfully with the specified model path and device configuration