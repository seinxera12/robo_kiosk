# Implementation Plan: Real-Time Streaming Voice Chatbot

## Overview

This implementation plan creates a fully self-hosted, bilingual (English + Japanese) real-time streaming voice chatbot system for kiosk deployment. The system achieves sub-600ms Time-to-First-Audio through aggressive pipeline parallelization, sentence-boundary TTS streaming, and a three-tier LLM fallback chain (vLLM → Ollama → Grok API).

The architecture separates concerns: Python kiosk client handles all I/O (audio capture, VAD, playback, UI), while the GPU inference server executes all AI processing (STT, LLM, TTS, RAG).

**Implementation Language**: Python 3.11+

**Key Technologies**: FastAPI, PyQt6, faster-whisper, ChromaDB, vLLM, Ollama, CosyVoice2, VOICEVOX

## Tasks

### Group A: Infrastructure & Configuration

- [x] 1. Set up repository structure and configuration management
  - Create directory structure: client/, server/, building_kb/, models/, scripts/
  - Create server/config.py with environment variable loading for all services
  - Create client/config.py with WebSocket URL and kiosk metadata
  - Create .env.example documenting all configuration options
  - Create .gitignore for models/, __pycache__, .env
  - _Requirements: 22.1, 22.2, 22.3, 22.4, 22.5_

- [x] 2. Create Docker Compose infrastructure
  - Write docker-compose.yml with services: voice-server, vllm, ollama, voicevox, searxng
  - Configure GPU access via NVIDIA Container Toolkit for voice-server and vllm
  - Set up volume mounts for models/, building_kb/, ChromaDB persistence
  - Configure service networking and port mappings
  - Add health checks for all services
  - _Requirements: 20.1, 20.2, 20.3, 20.4, 20.5, 20.6, 20.7, 20.8, 20.9, 23.6_

- [x] 3. Create server Dockerfile
  - Write server/Dockerfile with Python 3.11, CUDA support
  - Install system dependencies: libsndfile, ffmpeg, CUDA libraries
  - Copy requirements.txt and install Python dependencies
  - Set up working directory and entry point
  - _Requirements: 20.1, 20.3_

### Group B: Server Core Pipeline

- [x] 4. Implement FastAPI WebSocket server
  - [x] 4.1 Create server/main.py with FastAPI application
    - Set up FastAPI app with CORS middleware
    - Implement /ws WebSocket endpoint
    - Implement /health HTTP endpoint for health checks
    - Add connection handling and error logging
    - _Requirements: 3.1, 3.7, 23.1, 23.4, 23.5_
  
  - [x] 4.2 Implement WebSocket message validation
    - Create message schema validation for upstream messages (session_start, text_input, interrupt)
    - Implement validate_and_sanitize_input function with security checks
    - Add input length limits (audio: 30s max, text: 1000 chars max)
    - Add rate limiting (10 requests/minute per kiosk)
    - _Requirements: 25.2, 25.3, 25.4, 25.5_

- [x] 5. Implement async pipeline orchestrator
  - [x] 5.1 Create server/pipeline.py with PipelineState dataclass
    - Define PipelineState with asyncio queues (audio_input, transcript, token, audio_output)
    - Add interrupt_event (asyncio.Event) for barge-in handling
    - Add conversation_history list (max 10 turns)
    - Add status tracking (listening/thinking/speaking/idle)
    - _Requirements: 15.4, 15.5, 15.6_
  
  - [x] 5.2 Implement VoicePipeline class with worker coroutines
    - Create audio_input_worker for STT processing
    - Create llm_worker for LLM inference with RAG
    - Create tts_worker for sentence-boundary synthesis
    - Create websocket_receiver for handling upstream messages
    - Implement run() method to launch all workers with asyncio.gather
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_
  
  - [x] 5.3 Implement barge-in interrupt handling
    - Implement handle_interrupt function to set interrupt_event
    - Add queue draining logic for all pipeline queues
    - Reset pipeline state to "listening" after interrupt
    - Send status update to client
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7_

### Group C: Server STT (Speech-to-Text)

- [x] 6. Implement Whisper STT module
  - [x] 6.1 Create server/stt/whisper_stt.py with WhisperSTT class
    - Initialize faster-whisper WhisperModel with large-v3-turbo
    - Configure greedy decoding (beam_size=1) for minimum latency
    - Set compute_type based on VRAM (float16 for ≥12GB, int8 for <12GB)
    - Implement transcribe() async method returning TranscriptionResult
    - Extract language and confidence from Whisper metadata
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 24.3, 24.4_
  
  - [x] 6.2 Create server/stt/text_cleaner.py with text cleaning functions
    - Implement strip_whitespace function
    - Implement remove_filler_words with language-specific lists (EN: "um", "uh"; JP: "えー", "あの")
    - Implement restore_punctuation for sentence endings
    - Create clean_transcript function combining all cleaning steps
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 18.6_

### Group D: Server Language Detection

- [x] 7. Implement language detection module
  - Create server/lang/detector.py with detect_from_unicode function
  - Implement Unicode block scanning for Japanese characters (U+3000-U+9FFF, U+FF00-U+FFEF)
  - Implement detect_language function with Whisper primary, Unicode fallback
  - Use confidence threshold of 0.8 for Whisper detection
  - Return "ja" if Japanese ratio > 0.2, else "en"
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

### Group E: Server RAG (Retrieval-Augmented Generation)

- [x] 8. Implement RAG embedder
  - Create server/rag/embedder.py with Embedder class
  - Load intfloat/multilingual-e5-large model on CPU
  - Implement encode() method with E5 instruction prefix ("query: ")
  - Return L2-normalized 1024-dim embeddings
  - _Requirements: 7.2, 24.6_

- [x] 9. Implement ChromaDB knowledge base
  - [x] 9.1 Create server/rag/chroma_store.py with BuildingKB class
    - Initialize ChromaDB PersistentClient with configurable path
    - Create or get "building_kb" collection
    - Implement ingest() method for document chunks with metadata
    - Store metadata: lang, floor, type (floor/facility/room/emergency)
    - _Requirements: 7.1, 7.7, 20.9_
  
  - [x] 9.2 Implement RAG retrieval with language filtering
    - Implement retrieve() async method with query embedding
    - Query ChromaDB with language filter (where={"lang": lang})
    - Return top-3 most relevant chunks concatenated
    - Complete retrieval within 30ms target
    - _Requirements: 7.3, 7.4, 7.6, 17.3_
  
  - [x] 9.3 Implement parallel RAG execution
    - Launch RAG retrieval as asyncio.create_task during STT processing
    - Await RAG result when building LLM prompt
    - Ensure RAG completes before LLM starts
    - _Requirements: 7.5, 17.6_

### Group F: Server LLM Fallback Chain

- [x] 10. Implement LLM backend base interface
  - Create server/llm/base_backend.py with BaseLLMBackend Protocol
  - Define ping() async method for health checks
  - Define stream() async method returning AsyncIterator[str]
  - Add type hints for messages and tools parameters
  - _Requirements: 8.1, 8.2, 8.3, 8.4_

- [x] 11. Implement vLLM backend
  - Create server/llm/vllm_backend.py with VLLMBackend class
  - Initialize AsyncOpenAI client with VLLM_BASE_URL from config
  - Implement ping() using models.list() endpoint
  - Implement stream() with streaming chat completions
  - Support tool calls via tools parameter
  - Use max_tokens=512, temperature=0.7
  - _Requirements: 8.1, 8.8, 8.9, 17.4_

- [x] 12. Implement Ollama backend
  - Create server/llm/ollama_backend.py with OllamaBackend class
  - Initialize AsyncOpenAI client with OLLAMA_BASE_URL from config
  - Implement ping() using models.list() endpoint
  - Implement stream() with streaming chat completions
  - Use Qwen2.5-7B-Instruct model
  - _Requirements: 8.2, 8.8, 8.9_

- [x] 13. Implement Grok API backend
  - Create server/llm/grok_backend.py with GrokBackend class
  - Initialize AsyncOpenAI client with xAI API base URL
  - Require GROK_API_KEY from environment
  - Implement ping() and stream() methods
  - Use grok-3-fast model
  - Log privacy warning when Grok is used
  - _Requirements: 8.3, 8.9, 8.10, 25.8_

- [x] 14. Implement LLM fallback chain orchestrator
  - [x] 14.1 Create server/llm/fallback_chain.py with LLMFallbackChain class
    - Initialize list of backends: [VLLMBackend, OllamaBackend, GrokBackend]
    - Add _healthy_index cache for last successful backend
    - Implement health_check() with 5-second timeout
    - _Requirements: 8.5, 8.6_
  
  - [x] 14.2 Implement stream_with_fallback method
    - Iterate through backends starting from _healthy_index
    - Perform health check before attempting each backend
    - Try streaming from backend, catch exceptions
    - Fall back to next backend on failure
    - Update _healthy_index on success
    - Raise RuntimeError if all backends fail
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.7, 16.4_

- [x] 15. Implement LLM prompt builder
  - Create server/llm/prompt_builder.py with build_messages function
  - Define SYSTEM_PROMPT_TEMPLATE with bilingual instructions
  - Include RAG context, datetime, kiosk location in system message
  - Instruct LLM to respond in same language as user
  - Instruct LLM to use polite form (です・ます体) for Japanese
  - Instruct LLM to provide landmark-based directions
  - Append last 10 conversation turns for context
  - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 15.5, 18.3, 18.7_

### Group G: Server TTS (Text-to-Speech)

- [x] 16. Implement TTS router
  - [x] 16.1 Create server/tts/tts_router.py with TTSRouter class
    - Implement get_engine() method routing by language
    - Route "en" to CosyVoice2, "ja" to VOICEVOX
    - Add fallback logic for VOICEVOX → Fish Speech
    - _Requirements: 10.1, 10.2, 10.3, 30.3_
  
  - [x] 16.2 Implement sentence-boundary streaming
    - Create stream_tts_with_sentence_boundaries function
    - Buffer tokens until sentence ending detected (.?!。？！…)
    - Require minimum 8 characters before synthesis
    - Synthesize and stream each complete sentence immediately
    - Flush remaining buffer after LLM completes
    - _Requirements: 10.4, 10.5, 10.7, 17.7_

- [x] 17. Implement CosyVoice2 TTS engine
  - Create server/tts/cosyvoice_tts.py with CosyVoiceTTS class
  - Load CosyVoice2-0.5B model on GPU (~1GB VRAM)
  - Implement synthesize_stream() async method
  - Stream audio chunks as generated
  - Achieve ~150ms TTFA for first sentence
  - _Requirements: 10.1, 10.9, 17.5, 24.5_

- [x] 18. Implement VOICEVOX TTS engine
  - Create server/tts/voicevox_tts.py with VoicevoxTTS class
  - Initialize with VOICEVOX base URL (http://voicevox:50021)
  - Implement health_check() method
  - Implement synthesize_stream() with two-step API (audio_query → synthesis)
  - Use configurable speaker ID (default: 1)
  - Return WAV audio bytes
  - _Requirements: 10.2, 20.5, 23.3_

- [x] 19. Implement Fish Speech TTS fallback
  - Create server/tts/fish_speech_tts.py with FishSpeechTTS class
  - Load Fish Speech v1.5 model on GPU
  - Implement synthesize_stream() for Japanese text
  - Use as fallback when VOICEVOX unavailable
  - _Requirements: 10.3, 30.3_

- [x] 20. Implement Opus audio encoding
  - Add Opus encoding to TTS output pipeline
  - Encode audio at 48kHz, mono, 20ms frames
  - Use VOIP application mode for speech optimization
  - Achieve ~80% bandwidth reduction vs PCM16
  - _Requirements: 10.8, 26.2, 26.3, 26.4, 26.6, 26.7_

### Group H: Server Web Search

- [x] 21. Implement SearXNG web search client
  - Create server/search/searxng_client.py with searxng_search function
  - Send GET requests to http://searxng:8080/search
  - Return top 3 results with titles and content
  - Set 5-second timeout for requests
  - _Requirements: 19.3, 19.4, 19.5, 19.6, 19.7_

- [x] 22. Implement LLM tool definitions
  - Create server/tools/tool_definitions.py with WEB_SEARCH_TOOL schema
  - Define function schema for web_search tool
  - Add tool description and parameters
  - Integrate tool into LLM prompt builder
  - _Requirements: 19.1, 19.2_

### Group I: Client Application

- [x] 23. Implement client audio capture
  - Create client/audio_capture.py with AudioCapture class
  - Open sounddevice input stream at 16kHz, mono, PCM16
  - Emit 20ms frames (640 bytes) to asyncio queue
  - Handle microphone unavailable errors gracefully
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

- [x] 24. Implement client VAD (Voice Activity Detection)
  - [x] 24.1 Create client/vad.py with SileroVAD class
    - Load Silero VAD model (CPU-only)
    - Configure thresholds: speech=0.5, min_speech=250ms, min_silence=500ms
    - Process 20ms frames through VAD model
    - _Requirements: 2.1, 2.2, 2.3_
  
  - [x] 24.2 Implement VAD event emission
    - Emit speech_start when speech probability exceeds threshold for 250ms
    - Accumulate audio frames in buffer during speech
    - Emit speech_end when silence exceeds 500ms
    - Return accumulated audio buffer on speech_end
    - Reset buffer after speech_end
    - _Requirements: 2.2, 2.3, 2.4, 2.5, 2.6_

- [x] 25. Implement client WebSocket client
  - [x] 25.1 Create client/ws_client.py with WebSocketClient class
    - Establish persistent WebSocket connection to ws://server:8765/ws
    - Send binary PCM16 audio frames upstream
    - Send JSON control messages (session_start, text_input, interrupt)
    - Receive binary Opus audio and JSON events downstream
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_
  
  - [x] 25.2 Implement WebSocket reconnection logic
    - Detect connection loss and attempt reconnection
    - Use exponential backoff (1s, 2s, 4s, up to 30s max)
    - Send session_start message after reconnection
    - _Requirements: 3.6, 3.7, 3.8, 29.7_

- [x] 26. Implement client audio playback
  - [x] 26.1 Create client/audio_playback.py with AudioPlayback class
    - Decode Opus frames to PCM16 using opuslib
    - Play audio via sounddevice at 48kHz
    - Maintain 200ms audio buffer for smooth playback
    - _Requirements: 11.1, 11.2, 11.3, 11.5_
  
  - [x] 26.2 Implement buffer underrun protection
    - Detect buffer underruns during playback
    - Insert silence padding on underrun
    - Log warnings for debugging
    - _Requirements: 11.4_
  
  - [x] 26.3 Implement barge-in detection
    - Monitor VAD speech_start events during playback
    - Immediately stop playback on speech_start
    - Send interrupt JSON message to server
    - _Requirements: 12.1, 12.2_

- [x] 27. Implement client keyboard input
  - Create client/keyboard_input.py with KeyboardInput class
  - Capture keyboard events from physical keyboard
  - Validate text input (non-empty, max 1000 chars)
  - Send text_input JSON message on Enter/submit
  - Clear input field after submission
  - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6_

- [x] 28. Implement client PyQt6 UI
  - [x] 28.1 Create client/ui/app.py with main window
    - Create QMainWindow in fullscreen kiosk mode (no window chrome)
    - Set up main layout with conversation area, status indicator, input area
    - Apply Qt stylesheets from styles.qss
    - _Requirements: 14.1, 14.7_
  
  - [x] 28.2 Create client/ui/conversation_widget.py
    - Display conversation transcript with user queries and system responses
    - Update display on transcript events from server
    - Update display incrementally on llm_text_chunk events
    - Auto-scroll to latest message
    - _Requirements: 14.2, 14.4, 14.5_
  
  - [x] 28.3 Create client/ui/status_indicator.py
    - Display three visual states: 🟢 Listening, 🟡 Thinking, 🔵 Speaking
    - Update state based on status events from server
    - Use color-coded indicators for clear visibility
    - _Requirements: 14.3_
  
  - [x] 28.4 Create client/ui/keyboard_widget.py (optional)
    - Implement on-screen keyboard widget for touch input
    - Connect to keyboard input handler
    - Make widget toggleable/hideable
    - _Requirements: 14.6_
  
  - [x] 28.5 Create client/ui/styles.qss
    - Define Qt stylesheets for consistent visual appearance
    - Style conversation widget, status indicator, input fields
    - Use high-contrast colors for kiosk visibility
    - _Requirements: 14.7_

- [x] 29. Implement client main entry point
  - Create client/main.py with asyncio event loop
  - Initialize all client components (audio capture, VAD, WebSocket, playback, UI)
  - Connect components via asyncio queues
  - Handle graceful shutdown on SIGTERM/SIGINT
  - _Requirements: 3.7, 15.1, 15.2, 15.3_

### Group J: Building Knowledge Base

- [x] 30. Create sample building knowledge documents
  - [x] 30.1 Create English building knowledge documents
    - Create building_kb/floors/ with floor_01.md through floor_05.md
    - Create building_kb/facilities/ with elevators.md, restrooms.md, exits.md, cafeteria.md
    - Create building_kb/rooms/ with meeting_rooms.md, directory.md
    - Include floor numbers, room locations, facility descriptions
    - _Requirements: 7.7, 27.2_
  
  - [x] 30.2 Create Japanese building knowledge documents
    - Create building_kb/japanese/ with translated versions of all English documents
    - Maintain same structure and metadata as English versions
    - Use polite form (です・ます体) in descriptions
    - _Requirements: 7.7, 18.1, 18.2, 27.7_

- [x] 31. Implement knowledge base ingestion script
  - [x] 31.1 Create server/rag/ingest.py with ingestion script
    - Read markdown documents from building_kb/ directory
    - Chunk documents into appropriate sizes (200-500 tokens)
    - Extract metadata from document structure (language, floor, type)
    - _Requirements: 27.1, 27.2, 27.3, 27.4_
  
  - [x] 31.2 Implement document embedding and storage
    - Generate embeddings using multilingual-e5-large
    - Store chunks and embeddings in ChromaDB
    - Make script idempotent (safe to run multiple times)
    - _Requirements: 27.5, 27.6, 27.8_

### Group K: Scripts & Tooling

- [x] 32. Create model download script
  - Create scripts/download_models.sh
  - Download Whisper Large V3 Turbo weights
  - Download multilingual-e5-large weights
  - Download CosyVoice2-0.5B weights
  - Download Qwen2.5-7B-Instruct weights
  - Store in models/ directory with proper structure
  - Verify model integrity after download
  - _Requirements: 28.1, 28.2, 28.3, 28.4, 28.5, 28.6, 28.8_

- [x] 33. Create knowledge base ingestion script
  - Create scripts/ingest_kb.sh wrapper script
  - Run server/rag/ingest.py with proper environment
  - Handle ChromaDB path configuration
  - Log ingestion progress and results
  - _Requirements: 27.1, 27.8_

- [x] 34. Create kiosk OS setup script
  - Create scripts/setup_kiosk_os.sh for Ubuntu 22.04
  - Configure auto-login for kiosk user
  - Disable screen blanking and power management
  - Configure audio devices (ALSA/PulseAudio)
  - Set up systemd service for client application
  - _Requirements: 21.1, 21.2, 21.3, 21.4, 21.5, 21.6, 21.7_

- [x] 35. Create systemd service file
  - Create client/kiosk.service systemd unit file
  - Configure service to start after graphical.target, network-online.target, sound.target
  - Set DISPLAY=:0 and XDG_RUNTIME_DIR environment variables
  - Configure automatic restart on failure (3-second delay)
  - Enable service to start on boot
  - _Requirements: 21.1, 21.2, 21.3, 21.4, 21.5, 21.6, 21.7_

- [x] 36. Create Python requirements files
  - Create server/requirements.txt with all server dependencies
  - Create client/requirements.txt with all client dependencies
  - Pin versions for reproducible builds
  - Include: fastapi, uvicorn, websockets, faster-whisper, chromadb, sentence-transformers, openai, httpx, torch, sounddevice, PyQt6, silero-vad, opuslib, numpy
  - _Requirements: 22.1, 22.2, 22.3, 22.4, 22.5_

- [x] 37. Create README and documentation
  - Create README.md with project overview
  - Document system requirements (GPU, VRAM, OS)
  - Document installation steps (Docker Compose, client setup)
  - Document configuration (environment variables)
  - Document deployment (server startup, client systemd service)
  - Include troubleshooting section
  - _Requirements: 22.6, 22.7_

### Final Integration

- [x] 38. Integration and wiring
  - [x] 38.1 Wire server components together
    - Connect STT → Language Detection → RAG → LLM → TTS pipeline
    - Integrate LLM fallback chain into pipeline
    - Integrate web search tool into LLM
    - Connect all components via asyncio queues
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 8.1, 8.2, 8.3, 19.1, 19.2_
  
  - [x] 38.2 Wire client components together
    - Connect audio capture → VAD → WebSocket → playback pipeline
    - Connect keyboard input → WebSocket
    - Connect WebSocket events → UI updates
    - Implement barge-in interrupt flow
    - _Requirements: 1.1, 1.2, 2.1, 2.2, 3.1, 11.1, 12.1, 13.1, 14.1_
  
  - [x] 38.3 Configure logging and monitoring
    - Set up structured logging with timestamps and log levels
    - Log all WebSocket connections/disconnections
    - Log all STT transcriptions with language and confidence
    - Log all LLM backend health checks and failovers
    - Log all TTS synthesis requests and durations
    - Log all errors with full stack traces
    - Log all VAD events and reconnection attempts
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 16.6, 16.7, 29.1, 29.2, 29.3, 29.4, 29.5, 29.6, 29.7, 29.8, 29.9_

- [x] 39. Final checkpoint - System integration verification
  - Verify all server components start successfully via Docker Compose
  - Verify client connects to server and establishes WebSocket
  - Verify end-to-end voice turn: audio capture → STT → LLM → TTS → playback
  - Verify keyboard text input flow
  - Verify barge-in interrupt handling
  - Verify LLM fallback chain (test with vLLM down)
  - Verify bilingual support (test English and Japanese queries)
  - Verify RAG retrieval returns relevant building information
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks are organized by dependency groups (A through K) following the implementation spec
- Each task references specific requirements for traceability
- Testing is a separate phase and not included in implementation tasks
- Full features from the start: bilingual support, complete fallback chain, full UI
- System achieves sub-600ms TTFA through aggressive parallelization
- All AI processing on GPU server, all I/O on CPU client
- Privacy-focused: fully self-hosted except Grok API fallback
