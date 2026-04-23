# Bugfix Requirements Document

## Introduction

The CosyVoice TTS synthesis fails when calling the `/synthesize` endpoint due to incorrect data type being passed to the `inference_zero_shot()` method. The current code reads a WAV file using `soundfile.read()` which returns a numpy array, but the CosyVoice API expects the prompt_wav parameter to be a file path string, torch.Tensor, raw bytes, or file-like object - not a numpy array.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN the `/synthesize` endpoint is called THEN the system crashes with "Failed to create AudioDecoder for [0. 0. 0. ... 0. 0. 0.]: Unknown source type: <class 'numpy.ndarray'>. Supported types are str, Path, bytes, Tensor and file-like objects."

1.2 WHEN `sf.read("prompt.wav", dtype="float32")` is executed THEN the system returns a numpy array that is incompatible with the `inference_zero_shot()` method

### Expected Behavior (Correct)

2.1 WHEN the `/synthesize` endpoint is called THEN the system SHALL successfully synthesize speech without crashing

2.2 WHEN the prompt audio is provided to `inference_zero_shot()` THEN the system SHALL accept the prompt_wav parameter as a file path string (e.g., "prompt.wav") or properly formatted torch.Tensor

### Unchanged Behavior (Regression Prevention)

3.1 WHEN the synthesis completes successfully THEN the system SHALL CONTINUE TO return WAV audio bytes in the response

3.2 WHEN valid text input is provided THEN the system SHALL CONTINUE TO generate speech with the same audio quality and characteristics

3.3 WHEN the model processes the prompt text and audio THEN the system SHALL CONTINUE TO use zero-shot inference for voice cloning

3.4 WHEN other API endpoints are called THEN the system SHALL CONTINUE TO function normally (health check, speakers list, etc.)