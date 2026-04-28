End-to-End Code Flow

Startup — Server Side
```
server/main.py  (entry point)
  └── FastAPI lifespan() runs once at boot
        ├── server/stt/whisper_stt.py      → WhisperSTT loaded into app_state["stt"]
        ├── server/llm/fallback_chain.py   → LLMFallbackChain loaded into app_state["llm_chain"]
        │     ├── server/llm/vllm_backend.py    (skipped if VLLM_MODEL_NAME=disabled)
        │     ├── server/llm/ollama_backend.py
        │     └── server/llm/grok_backend.py    (skipped if no GROK_API_KEY)
        ├── server/rag/chroma_store.py     → BuildingKB loaded into app_state["rag"]
        │     └── server/rag/embedder.py        (sentence-transformer, shared with intent classifier)
        └── server/tts/tts_router.py       → TTSRouter loaded into app_state["tts_router"]
              ├── server/tts/kokoro_tts.py       KokoroTTS (English primary, lazy-loads on first use)
              ├── server/tts/cosyvoice_tts.py    CosyVoiceTTS (English fallback, HTTP to :5002)
              ├── server/tts/kokoro_tts.py       KokoroJapaneseTTS (Japanese primary)
              ├── server/tts/voicevox_tts.py     VoicevoxTTS (Japanese fallback, HTTP to :50021)
              └── server/tts/fish_speech_tts.py  FishSpeechTTS (last resort, placeholder)
```
Everything is pre-loaded once. WebSocket connections get the already-warm instances — no cold start per user.

Startup — Client Side
```
client/main.py  (entry point, --text / --no-ui / default)
  └── client/config.py   → ClientConfig.from_env()
        ├── --text mode   → run_headless_text()
        ├── --no-ui mode  → run_headless()  (mic + VAD)
        └── default       → run_qt()
              └── client/ui/app.py   KioskMainWindow (PyQt6)

```
Per-Connection — WebSocket Handshake
```
client/ws_client.py  WebSocketClient.connect()
  └── sends JSON: { type: "session_start", kiosk_id, kiosk_location }

server/main.py  websocket_endpoint()
  └── server/pipeline.py  VoicePipeline.__init__()
        └── server/llm/intent_classifier.py  IntentClassifier()
              └── reuses rag.embedder — no second model load
```
Per-Turn — The 5 Concurrent Workers
```
VoicePipeline.run() launches all five with asyncio.gather(). They communicate through async queues:

audio_input  →[audio_input queue]→  llm_worker
                                         ↓
                                   [transcript queue]
                                         ↓
                                     llm_worker
                                         ↓
                                    [token queue]
                                         ↓
                                     tts_worker
                                         ↓
                                  [audio_output queue]
                                         ↓
                                  audio_output_worker
                                         ↓
                                    WebSocket → client

```
Worker 1 — websocket_receiver (in pipeline.py)
```
Receives raw bytes or JSON from WebSocket
  ├── bytes  → puts raw PCM16 audio into audio_input queue
  └── JSON   → handles session_start, text_input, interrupt events
```
Worker 2 — audio_input_worker
(in pipeline.py)
```
Gets PCM16 bytes from audio_input queue
  └── server/stt/whisper_stt.py  WhisperSTT.transcribe()
        ├── converts bytes → float32 numpy array
        ├── runs WhisperModel.transcribe() in thread pool (non-blocking)
        ├── server/lang/detector.py  detect_language()
        │     uses Whisper's detected lang if confidence ≥ 0.8,
        │     else falls back to Unicode character scan
        └── returns TranscriptionResult { text, language, confidence, duration_ms }
              └── puts result into transcript queue
              └── sends JSON { type: "transcript", text, lang } back to client
```
Worker 3 — llm_worker (in pipeline.py)

Gets TranscriptionResult from transcript queue
```
  │
  ├── server/llm/intent_classifier.py  IntentClassifier.classify()
  │     Tier 1: keyword rules (zero latency)
  │     Tier 1b: history carry-over check
  │     Tier 2: embedding cosine similarity (uses rag.embedder)
  │     Returns: ClassificationResult { intent: BUILDING | SEARCH | GENERAL }
  │
  ├── [if BUILDING + use_rag=true]
  │     server/rag/chroma_store.py  BuildingKB.retrieve()
  │       └── server/rag/embedder.py  Embedder.encode(query)
  │             → ChromaDB query with language filter
  │             → returns top-3 chunks as concatenated string
  │
  ├── [if SEARCH]
  │     server/search/query_reformulator.py  extract_search_query()
  │       └── synchronous Ollama call (qwen2.5:3b, max 32 tokens)
  │             → returns concise 3-6 word English query
  │     server/search/searxng_client.py  searxng_search()
  │       └── async HTTP GET to SearXNG :8081
  │             → returns list of { title, content, url }
  │     server/llm/prompt_builder.py  format_search_context()
  │       → formats results into a context block string
  │
  ├── server/llm/prompt_builder.py  build_messages()
  │     selects system prompt template (BUILDING / SEARCH / GENERAL)
  │     injects context, datetime, kiosk location, language rule
  │     trims history to fit token budget (~3000 tokens)
  │     returns list of { role, content } dicts
  │
  └── server/llm/fallback_chain.py  LLMFallbackChain.stream_with_fallback()
        tries backends in order: vLLM → Ollama → Grok
          └── server/llm/ollama_backend.py  OllamaBackend.stream()
                → async HTTP streaming to Ollama :11434
                → yields tokens one by one
        each token:
          ├── put into token queue (for tts_worker)
          └── sent as JSON { type: "llm_text_chunk", text, final: false } to client
        on completion:
          ├── sends { type: "llm_text_chunk", text: "", final: true }
          ├── puts None sentinel into token queue (signals tts_worker to flush)
          └── appends { role: user/assistant, content, lang } to conversation_history
```
Worker 4 — tts_worker (in pipeline.py)
```
Drains token queue, accumulates into buffer
  └── waits for sentence boundary: . ? ! 。 ？ ！ … (or None sentinel = flush)
        └── server/tts/tts_router.py  TTSRouter.get_engine(lang)
              ├── "en" → KokoroTTS  (or CosyVoiceTTS if Kokoro unavailable)
              └── "ja" → KokoroJapaneseTTS  (or VoicevoxTTS → FishSpeechTTS)

        [English path]
        server/tts/kokoro_tts.py  KokoroTTS.synthesize_stream(sentence)
          ├── lazy-loads KPipeline on first call (downloads ~330MB from HF once)
          ├── splits sentence further if needed (_split_sentences)
          ├── runs KPipeline() in _kokoro_executor (single-threaded, non-blocking)
          └── yields WAV bytes (24kHz PCM16) per sentence segment

        [Japanese path]
        server/tts/kokoro_tts.py  KokoroJapaneseTTS.synthesize_stream(sentence)
          └── same pattern, lang_code='j', _split_sentences_ja()

        [English fallback]
        server/tts/cosyvoice_tts.py  CosyVoiceTTS.synthesize_stream(sentence)
          └── async HTTP POST to CosyVoice service :5002/synthesize
                → streams WAV chunks back via chunked HTTP transfer

        Each WAV chunk → put into audio_output queue

Worker 5 — audio_output_worker (in pipeline.py)

Gets WAV bytes from audio_output queue
  └── sends raw bytes over WebSocket to client

```
Client — Receiving Audio

```json
client/ws_client.py  WebSocketClient.receive()
  └── yields bytes (WAV) or dict (JSON)

[headless/UI mode]
  ├── bytes → client/audio_playback.py  AudioPlayback.queue_audio()
  │             ├── decodes WAV → PCM16 numpy
  │             └── _playback_loop() writes to sounddevice OutputStream
  │                   (all sounddevice calls go through _playback_executor,
  │                    single-threaded to avoid ALSA thread-safety issues)
  └── dict  → prints text chunks to terminal / updates UI
```
Client — Sending Audio (headless/UI mode)

```
client/audio_capture.py  AudioCapture.stream()
  └── sounddevice InputStream callback → yields AudioFrame (32ms PCM16)

client/vad.py  SileroVAD.process_frame(frame)
  └── Silero VAD model (CPU) → speech probability per frame
        ├── speech_start → starts buffering
        ├── speech_chunk → accumulates into speech_buffer
        └── speech_end   → returns VADEvent with full audio_buffer

client/ws_client.py  WebSocketClient.send_audio(audio_buffer)
  └── sends raw PCM16 bytes over WebSocket to server

```

Interrupt / Barge-in

```
Client sends JSON: { type: "interrupt" }
  └── websocket_receiver sets state.interrupt_event
        └── all workers check interrupt_event at top of their loops
              → pause processing, drain queues, clear event
              → resume listening
```

Summary — Data Types Flowing Through the System
```
Queue / Channel	What travels
audio_input queue	bytes — raw PCM16 from client
transcript queue	TranscriptionResult — text + language + confidence
token queue	str tokens, then None sentinel
audio_output queue	bytes — WAV chunks from TTS
WebSocket (client→server)	bytes PCM16 audio, or JSON control messages
WebSocket (server→client)	bytes WAV audio, or JSON text/status messages
```