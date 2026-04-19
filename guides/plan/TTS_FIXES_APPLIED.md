# TTS Fixes Applied

## Critical Bugs Fixed

### 1. **Missing Audio Output Worker** (CRITICAL)

**Problem:** TTS audio was being synthesized and put into `audio_output` queue, but **never sent to the client**. The audio just sat in the queue forever.

**Fix:** Added `audio_output_worker()` that:
- Consumes audio chunks from `audio_output` queue
- Sends them to client via WebSocket as binary messages
- Handles errors gracefully

**Impact:** TTS audio now actually reaches the client!

### 2. **TTS Worker Loop Bug** (CRITICAL)

**Problem:** `tts_worker()` would process ONE sentence then exit the inner loop, never processing subsequent sentences.

**Fix:** Restructured the loop to:
- Continuously process tokens from the queue
- Use timeout to detect end of stream
- Flush remaining buffer when no more tokens
- Continue processing multiple sentences

**Impact:** Multi-sentence responses now work correctly!

### 3. **Missing TTS Engine Null Check**

**Problem:** If TTS engine failed to load, `get_engine()` returns `None`, but code tried to call `synthesize_stream()` on it → crash.

**Fix:** Added null check:
```python
if tts_engine is None:
    logger.warning(f"No TTS engine available for language: {current_lang}")
    continue
```

**Impact:** Server doesn't crash if TTS engine unavailable.

### 4. **Client WAV Decoding Missing**

**Problem:** Client `audio_playback.py` expected Opus but TTS engines send WAV. No decoding logic existed.

**Fix:** Implemented `_decode_wav()` that:
- Parses WAV headers
- Extracts PCM data
- Detects sample rate dynamically
- Handles both CosyVoice (22050 Hz) and VOICEVOX (24000 Hz)

**Impact:** Client can now play audio from both TTS engines!

### 5. **Language Detection for TTS**

**Problem:** `tts_worker` used `self.state.current_turn.get("lang", "en")` which could fail if `current_turn` is None.

**Fix:** Safer language detection:
```python
current_lang = "en"
if self.state.current_turn and "lang" in self.state.current_turn:
    current_lang = self.state.current_turn["lang"]
```

**Impact:** No crashes when processing first request.

## Files Modified

| File | Changes |
|------|---------|
| `server/pipeline.py` | Added `audio_output_worker()`, fixed `tts_worker()` loop, added null checks |
| `client/audio_playback.py` | Implemented WAV decoding, updated sample rate handling |

## How It Works Now

### Server Side (Pipeline Flow)

```
1. STT detects language (en/ja)
2. LLM generates response tokens
3. tts_worker:
   - Collects tokens until sentence boundary
   - Gets TTS engine for detected language
   - Synthesizes audio (WAV)
   - Puts WAV bytes in audio_output queue
4. audio_output_worker:
   - Consumes WAV bytes from queue
   - Sends to client via WebSocket (binary)
```

### Client Side (Playback Flow)

```
1. Receives binary WebSocket message (WAV bytes)
2. audio_playback.queue_audio():
   - Decodes WAV headers
   - Extracts PCM data
   - Queues for playback
3. _start_playback():
   - Opens audio stream
   - Plays PCM data
   - Continues until queue empty
```

## Language Routing

| Language | TTS Engine | Sample Rate | Output Format |
|----------|------------|-------------|---------------|
| English (`en`) | CosyVoice2 | 22050 Hz | WAV (PCM16) |
| Japanese (`ja`) | VOICEVOX | 24000 Hz | WAV (PCM16) |

The client dynamically adjusts sample rate based on WAV headers.

## Testing

### Test English TTS

```bash
# Start server
python -m uvicorn server.main:app --reload

# In another terminal, test with client
python client/main.py --text

# Type: Hello, how are you?
# Expected: Hear English voice
```

### Test Japanese TTS

```bash
# Type: こんにちは
# Expected: Hear Japanese voice
```

### Check Logs

```bash
# Server logs should show:
# - "audio_output_worker started"
# - "Sending X bytes of audio to client"
# - "Audio chunk sent successfully"

# Client logs should show:
# - "Decoded WAV: 22050Hz, 1ch, 2B, X bytes"
# - "Starting audio playback"
```

## Verification Checklist

- [x] Server starts without errors
- [x] `audio_output_worker` is running
- [x] TTS audio is synthesized
- [x] Audio is sent to client via WebSocket
- [x] Client decodes WAV correctly
- [x] Audio plays through speakers
- [x] Multi-sentence responses work
- [x] Both English and Japanese TTS work
- [x] Graceful fallback if TTS engine unavailable

## Known Limitations

1. **No streaming within sentence** — Audio is sent after full sentence synthesis (not chunk-by-chunk during synthesis)
2. **No Opus encoding** — Sending WAV (larger bandwidth than Opus)
3. **No resampling** — Client must support 22050 Hz and 24000 Hz

## Future Enhancements

1. **Opus encoding** — Reduce bandwidth by 80%
2. **Streaming synthesis** — Send audio chunks as they're generated
3. **Resampling** — Normalize to single sample rate (48000 Hz)
4. **Audio buffering** — Pre-buffer audio to reduce latency

## Debugging

### No Audio Heard

1. Check server logs for "audio_output_worker started"
2. Check for "Sending X bytes of audio to client"
3. Check client logs for "Decoded WAV"
4. Check client logs for "Starting audio playback"
5. Verify speakers are working: `python -c "import sounddevice as sd; sd.play([0.5]*8000, 8000); sd.wait()"`

### Audio Garbled

1. Check sample rate mismatch in logs
2. Verify WAV decoding: `Decoded WAV: XXXXHz, 1ch, 2B`
3. Check for buffer underruns

### TTS Not Working

1. Check `/health` endpoint: `curl http://localhost:8765/health | jq .tts`
2. Check for "No TTS engine available" warnings
3. Verify CosyVoice/VOICEVOX are loaded

## Summary

All critical TTS bugs are now fixed:
- ✅ Audio is sent to client
- ✅ Multi-sentence responses work
- ✅ WAV decoding implemented
- ✅ Both English and Japanese TTS functional
- ✅ Graceful error handling

The TTS pipeline is now **fully operational**!
