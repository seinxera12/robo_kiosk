Code Analysis: cosyvoice_service/app.py
Overall verdict: The architecture is sound, but there are several significant bugs that will cause runtime failures or produce broken audio. Here's the full breakdown.

🔴 Critical Bugs
1. stream=False defeats the entire streaming architecture
The StreamingResponse wrapper implies real-time audio delivery, but the inference call contradicts it:
python# Current code — generates entire audio THEN iterates
output = cosyvoice_model.inference_cross_lingual(
    ...
    stream=False,   # ← blocks until ALL audio is ready
    ...
)
With stream=False, the model generates the full utterance before the for loop even begins. The StreamingResponse only streams the already-complete WAV blobs to the HTTP client — there is no actual low-latency synthesis. You need stream=True:
pythonoutput = cosyvoice_model.inference_cross_lingual(
    tts_text=tagged_text,
    prompt_speech_16k=prompt_wav,
    stream=True,   # ← yields audio chunks as tokens are decoded
    speed=speed
)

2. Multiple WAV headers in the stream — broken audio
Each chunk is independently encoded as a full WAV file with its own 44-byte header:
python# This runs once per chunk, producing WAV header + data EVERY time:
wav_bytes = audio_to_wav(data, sample_rate=24000)
yield wav_bytes
When a client receives this stream, it gets:
[RIFF header][PCM data][RIFF header][PCM data][RIFF header]...
No standard audio player or browser <audio> element can parse this. It will either play only the first chunk, crash, or produce garbled audio.
The correct approach is to either stream raw PCM (headerless), or build a single WAV by writing the header once and concatenating PCM data:
pythonasync def generate():
    loop = asyncio.get_running_loop()
    chunk_queue = asyncio.Queue()
    first_chunk = True
    sample_rate = cosyvoice_model.sample_rate  # use model's actual rate

    def _run_synthesis():
        try:
            for audio_chunk in cosyvoice_model.inference_cross_lingual(
                tts_text=tagged_text,
                prompt_speech_16k=prompt_wav,
                stream=True,
                speed=speed
            ):
                data = audio_chunk['tts_speech']
                if hasattr(data, 'cpu'):
                    data = data.cpu().numpy().squeeze()
                pcm = (data * 32767).astype(np.int16).tobytes()
                loop.call_soon_threadsafe(chunk_queue.put_nowait, pcm)
        except Exception as e:
            logger.error(f"Synthesis error: {e}", exc_info=True)
        finally:
            loop.call_soon_threadsafe(chunk_queue.put_nowait, None)

    asyncio.get_event_loop().run_in_executor(_executor, _run_synthesis)

    # Yield raw PCM — client handles reassembly
    while True:
        chunk = await chunk_queue.get()
        if chunk is None:
            break
        yield chunk
Then change the response media type:
pythonreturn StreamingResponse(
    generate(),
    media_type="audio/pcm",   # or audio/L16;rate=24000
    headers={"X-Sample-Rate": str(cosyvoice_model.sample_rate)}
)

3. Wrong parameter name for inference_cross_lingual
The CosyVoice2 AutoModel API signature uses positional or prompt_speech_16k, not prompt_wav:
python# Your code — keyword arg 'prompt_wav' does not exist in AutoModel
cosyvoice_model.inference_cross_lingual(
    tts_text=tagged_text,
    prompt_wav=prompt_wav,      # ← will raise TypeError
    ...
)
The correct call is:
pythoncosyvoice_model.inference_cross_lingual(
    tts_text=tagged_text,
    prompt_speech_16k=prompt_wav,  # ← correct param name
    stream=True,
    speed=speed
)
Note also that AutoModel may expect the wav to be pre-loaded as a tensor, not a file path string. The safe approach:
pythonfrom cosyvoice.utils.file_utils import load_wav

prompt_speech_16k = load_wav(cross_lingual_wav, 16000)  # load once at startup

🟠 Significant Issues
4. Sample rate hardcoded incorrectly
pythondef audio_to_wav(audio_data, sample_rate: int = 22050):  # default: 22050
    ...

wav_bytes = audio_to_wav(data, sample_rate=24000)  # called with: 24000
The default and the call site are inconsistent. Worse, neither should be hardcoded — CosyVoice2 operates at 22050 Hz (despite some docs saying 24000), and the truth is always in:
pythoncosyvoice_model.sample_rate  # use this everywhere

5. /speakers endpoint will fail for CosyVoice2-0.5B
pythonavailable_speakers = list(cosyvoice_model.frontend.spk2info.keys())
spk2info exists only on SFT-style models (CosyVoice-300M-SFT). CosyVoice2-0.5B is a zero-shot model — it has no preset speakers, so frontend.spk2info will either be an empty dict or raise AttributeError. The speaker_id field in SynthesisRequest is also accepted but silently ignored throughout the synthesis logic — it's dead code.
Either remove these, or replace with a note that voice is controlled via a reference wav:
python@app.get("/speakers")
async def list_speakers():
    return {
        "note": "CosyVoice2-0.5B is a zero-shot model. Voice is controlled by reference audio.",
        "mode": "cross_lingual",
        "language_tags": ["<|en|>", "<|jp|>", "<|zh|>", "<|ko|>"]
    }

6. asyncio.get_event_loop() inside async context
pythonasyncio.get_event_loop().run_in_executor(_executor, _run_synthesis)
Inside an async function in Python 3.10+, the correct call is:
pythonloop = asyncio.get_running_loop()
await loop.run_in_executor(_executor, _run_synthesis)
Without await, the executor call is fire-and-forget — technically it still works here because you poll the queue, but the task lifecycle isn't properly managed and exceptions from the executor won't propagate.

7. No language selection — Japanese is unreachable
The SynthesisRequest has no language field, and the language tag is hardcoded:
pythontagged_text = f"<|en|>{request.text}"   # always English
For a bilingual English/Japanese chatbot, you need to expose this:
pythonclass SynthesisRequest(BaseModel):
    text: str
    language: str = "en"   # "en" or "jp"
    speed: float = 1.0

# In synthesize():
lang_tag = {"en": "<|en|>", "jp": "<|jp|>"}.get(request.language, "<|en|>")
tagged_text = f"{lang_tag}{request.text}"

# Optionally use different reference wavs per language:
prompt_map = {"en": app.state.en_prompt_wav, "jp": app.state.jp_prompt_wav}
prompt_wav = prompt_map.get(request.language, app.state.en_prompt_wav)

🟡 Minor Issues
8. _executor shutdown called without await
python_executor.shutdown(wait=False)
This fires during lifespan teardown but doesn't wait for the running synthesis thread to complete. If a request is in-flight during shutdown, it'll be silently killed. Better to set a flag and wait gracefully.
9. audio_to_wav converts float32 to int16 without clipping
pythonaudio_int16 = (audio_data * 32767).astype(np.int16)
If the model outputs values outside [-1.0, 1.0] (it occasionally can), this overflows silently. Add:
pythonaudio_data = np.clip(audio_data, -1.0, 1.0)
audio_int16 = (audio_data * 32767).astype(np.int16)

✅ What's Done Well

Lifespan-based model loading is the correct FastAPI pattern — model loads once, safely.
ThreadPoolExecutor(max_workers=1) correctly serializes inference since the model isn't thread-safe.
Queue-based thread-to-async bridging (loop.call_soon_threadsafe) is the right pattern.
Path handling for cosyvoice_repo and Matcha-TTS submodule is correct.
Logging is well-placed throughout.


Summary Table
IssueSeverityImpactstream=False with StreamingResponse🔴 CriticalNo actual streaming; high first-token latencyMultiple WAV headers per chunk🔴 CriticalBroken audio output for clientsWrong prompt_wav param name🔴 CriticalTypeError at runtimeHardcoded/inconsistent sample rate🟠 SignificantAudio pitch/speed distortion/speakers broken for zero-shot model🟠 Significant500 error on endpointspeaker_id accepted but ignored🟠 SignificantSilent dead codeNo Japanese/language routing🟠 SignificantChatbot can't serve Japaneseget_event_loop() vs get_running_loop()🟡 MinorBad practice, potential edge-case failureNo audio clipping before int16 cast🟡 MinorRare overflow artifacts