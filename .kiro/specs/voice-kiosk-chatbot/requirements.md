# Requirements Document: Real-Time Streaming Voice Chatbot

## Introduction

This document specifies the requirements for a fully self-hosted, bilingual (English + Japanese) real-time streaming voice chatbot system designed for kiosk and robot deployment. The system provides building navigation assistance through voice and keyboard interaction, achieving sub-600ms Time-to-First-Audio (TTFA) through aggressive pipeline parallelization, sentence-boundary TTS streaming, and a three-tier LLM fallback chain.

The architecture follows a strict separation: the Python kiosk client handles all I/O operations (audio capture, VAD, playback, UI), while the GPU inference server executes all AI processing (STT, LLM, TTS, RAG).

## Glossary

- **Client**: Python desktop application running on Ubuntu 22.04 kiosk hardware (CPU-only)
- **Server**: GPU inference server running all AI pipelines (STT, LLM, TTS, RAG)
- **VAD**: Voice Activity Detection system (Silero VAD)
- **STT**: Speech-to-Text system (Whisper Large V3 Turbo)
- **LLM**: Large Language Model inference system with fallback chain
- **TTS**: Text-to-Speech synthesis system
- **RAG**: Retrieval-Augmented Generation knowledge base system
- **TTFA**: Time-to-First-Audio, measured from speech_end to first audio playback
- **PCM16**: 16-bit Pulse Code Modulation audio format
- **Opus**: Compressed audio codec for efficient transmission
- **WebSocket**: Bidirectional communication protocol between Client and Server
- **Barge-in**: User interruption during system audio playback
- **vLLM**: Primary LLM inference engine (local GPU)
- **Ollama**: Secondary LLM inference engine (local CPU/GPU)
- **Grok**: Tertiary LLM inference engine (cloud API fallback)
- **ChromaDB**: Vector database for RAG document storage
- **VOICEVOX**: Japanese TTS engine (Docker REST API)
- **CosyVoice2**: English TTS engine (0.5B model)
- **SearXNG**: Self-hosted web search service

## Requirements

### Requirement 1: Audio Input Capture

**User Story:** As a kiosk user, I want to speak naturally into the microphone, so that the system can understand my questions without requiring button presses.

#### Acceptance Criteria

1. THE Client SHALL capture audio from the microphone at 16kHz sample rate, mono channel, PCM16 format
2. THE Client SHALL process audio in 20ms frames (640 bytes per frame)
3. THE Client SHALL continuously capture audio while the application is running
4. WHEN the microphone is unavailable or fails, THEN THE Client SHALL log an error and display a user-friendly message
5. THE Client SHALL use ALSA or PulseAudio for audio capture on Ubuntu 22.04

### Requirement 2: Voice Activity Detection

**User Story:** As a kiosk user, I want the system to automatically detect when I start and stop speaking, so that I don't need to manually trigger recording.

#### Acceptance Criteria

1. THE Client SHALL run Silero VAD on each 20ms audio frame using CPU-only inference
2. WHEN speech probability exceeds 0.5 threshold for at least 250ms, THEN THE Client SHALL emit a speech_start event
3. WHEN speech probability falls below 0.5 threshold for at least 500ms during active speech, THEN THE Client SHALL emit a speech_end event
4. WHILE speech is active, THE Client SHALL accumulate audio frames in a buffer
5. WHEN speech_end is detected, THEN THE Client SHALL send the accumulated audio buffer to the Server via WebSocket
6. THE Client SHALL reset the audio buffer after sending to the Server

### Requirement 3: Client-Server Communication

**User Story:** As a system operator, I want reliable real-time communication between the client and server, so that voice interactions are processed with minimal latency.

#### Acceptance Criteria

1. THE Client SHALL establish a persistent WebSocket connection to the Server at ws://server:8765/ws
2. THE Client SHALL send binary PCM16 audio frames upstream to the Server
3. THE Client SHALL send JSON control messages upstream (session_start, text_input, interrupt)
4. THE Client SHALL receive binary Opus-encoded audio frames downstream from the Server
5. THE Client SHALL receive JSON event messages downstream (transcript, llm_text_chunk, status, tts_start, tts_end, error)
6. WHEN the WebSocket connection is lost, THEN THE Client SHALL attempt reconnection with exponential backoff (1s, 2s, 4s, up to 30s max)
7. THE Client SHALL send a session_start message immediately after WebSocket connection establishment
8. THE session_start message SHALL include kiosk_id and kiosk_location fields

### Requirement 4: Speech-to-Text Transcription

**User Story:** As a system, I want to accurately transcribe user speech in both English and Japanese, so that I can understand user queries regardless of language.

#### Acceptance Criteria

1. THE Server SHALL transcribe audio using Whisper Large V3 Turbo model via faster-whisper
2. THE Server SHALL use greedy decoding (beam_size=1) for minimum latency
3. THE Server SHALL automatically detect language (English or Japanese) during transcription
4. THE Server SHALL use float16 compute type on GPUs with ≥12GB VRAM
5. THE Server SHALL use int8 compute type on GPUs with <12GB VRAM
6. WHEN transcription completes, THEN THE Server SHALL return transcript text, detected language, and confidence score
7. THE Server SHALL complete transcription within 150ms for typical utterances (3-10 seconds of speech)
8. WHEN language confidence is ≥0.8, THEN THE Server SHALL use Whisper's detected language
9. WHEN language confidence is <0.8, THEN THE Server SHALL fall back to Unicode block scanning for language detection

### Requirement 5: Text Cleaning and Normalization

**User Story:** As a system, I want to clean transcribed text of filler words and formatting issues, so that downstream processing receives high-quality input.

#### Acceptance Criteria

1. THE Server SHALL strip leading and trailing whitespace from transcripts
2. THE Server SHALL remove English filler words ("um", "uh") from English transcripts
3. THE Server SHALL remove Japanese filler words ("えー", "あの") from Japanese transcripts
4. THE Server SHALL restore sentence-ending punctuation if missing
5. THE Server SHALL validate language detection using Unicode block scanning as a secondary check

### Requirement 6: Language Detection

**User Story:** As a system, I want to accurately detect the language of each user input, so that I can provide responses in the appropriate language.

#### Acceptance Criteria

1. THE Server SHALL detect language from Whisper transcription metadata as the primary method
2. WHEN Whisper confidence is <0.8, THEN THE Server SHALL use Unicode block scanning as fallback
3. THE Unicode scanner SHALL detect Japanese when ≥20% of characters are in Japanese Unicode blocks (U+3000-U+9FFF, U+FF00-U+FFEF)
4. THE Unicode scanner SHALL detect English when <20% of characters are in Japanese Unicode blocks
5. THE Server SHALL use the detected language for RAG retrieval, LLM prompt construction, and TTS routing
6. THE language detection SHALL be deterministic for identical inputs

### Requirement 7: Knowledge Base Retrieval (RAG)

**User Story:** As a kiosk user, I want the system to provide accurate information about building locations and facilities, so that I can navigate effectively.

#### Acceptance Criteria

1. THE Server SHALL store building knowledge documents in ChromaDB vector database
2. THE Server SHALL use intfloat/multilingual-e5-large embeddings for document indexing
3. WHEN a user query is received, THEN THE Server SHALL retrieve the top-3 most relevant document chunks
4. THE Server SHALL filter retrieved chunks by detected language (English or Japanese)
5. THE Server SHALL launch RAG retrieval in parallel with STT finalization to minimize latency
6. THE Server SHALL complete RAG retrieval within 30ms for typical queries
7. THE Server SHALL embed documents with metadata including language, floor number, and type (floor/facility/room/emergency)

### Requirement 8: LLM Inference with Fallback Chain

**User Story:** As a system operator, I want automatic failover between LLM backends, so that the system remains operational even when individual services fail.

#### Acceptance Criteria

1. THE Server SHALL attempt LLM inference using vLLM as the primary backend
2. WHEN vLLM is unavailable or fails health check, THEN THE Server SHALL fall back to Ollama
3. WHEN Ollama is unavailable or fails health check, THEN THE Server SHALL fall back to Grok API
4. WHEN all LLM backends fail, THEN THE Server SHALL return an error to the Client
5. THE Server SHALL perform health checks on each backend with a 5-second timeout
6. THE Server SHALL cache the last successful backend index to optimize subsequent requests
7. THE Server SHALL stream LLM tokens as they are generated (not batch responses)
8. THE Server SHALL use Qwen2.5-7B-Instruct model for vLLM and Ollama backends
9. THE Server SHALL use grok-3-fast model for Grok API backend
10. THE Server SHALL log a privacy warning when using Grok API (data leaves local network)

### Requirement 9: LLM Prompt Construction

**User Story:** As a system, I want to provide the LLM with relevant context and instructions, so that it generates helpful and accurate responses.

#### Acceptance Criteria

1. THE Server SHALL construct LLM prompts with a system message containing building knowledge context
2. THE system message SHALL instruct the LLM to respond in the same language as the user query
3. THE system message SHALL include retrieved RAG context chunks
4. THE system message SHALL include current date/time and kiosk location
5. THE Server SHALL include the last 10 conversation turns in the prompt for context
6. THE Server SHALL append the current user query as the final message
7. THE system message SHALL instruct the LLM to use polite form (です・ます体) for Japanese responses
8. THE system message SHALL instruct the LLM to provide landmark-based directions rather than cardinal directions

### Requirement 10: Text-to-Speech Synthesis

**User Story:** As a kiosk user, I want to hear spoken responses in natural-sounding voices, so that I can understand the system's answers without reading.

#### Acceptance Criteria

1. THE Server SHALL route English text to CosyVoice2-0.5B TTS engine
2. THE Server SHALL route Japanese text to VOICEVOX TTS engine as primary
3. WHEN VOICEVOX is unavailable, THEN THE Server SHALL fall back to Fish Speech v1.5 for Japanese
4. THE Server SHALL synthesize audio sentence-by-sentence as LLM tokens arrive
5. WHEN a sentence boundary is detected (.?!。？！…) and sentence length ≥8 characters, THEN THE Server SHALL synthesize that sentence immediately
6. THE Server SHALL stream audio chunks to the Client as they are generated
7. THE Server SHALL flush any remaining text buffer after LLM completes
8. THE Server SHALL encode audio as Opus format before transmission to reduce bandwidth
9. THE Server SHALL achieve ~150ms TTFA for the first sentence

### Requirement 11: Audio Playback

**User Story:** As a kiosk user, I want to hear system responses clearly through the speaker, so that I can understand the information provided.

#### Acceptance Criteria

1. THE Client SHALL decode Opus-encoded audio frames to PCM16 format
2. THE Client SHALL play audio through ALSA or PulseAudio at 48kHz sample rate
3. THE Client SHALL buffer incoming audio chunks to prevent playback underruns
4. WHEN audio buffer underruns occur, THEN THE Client SHALL insert silence padding and log a warning
5. THE Client SHALL maintain a minimum 200ms audio buffer for smooth playback
6. THE Client SHALL play audio continuously until tts_end event is received

### Requirement 12: Barge-in Interrupt Handling

**User Story:** As a kiosk user, I want to interrupt the system while it's speaking, so that I can ask follow-up questions without waiting for long responses to finish.

#### Acceptance Criteria

1. WHEN the Client detects speech_start during audio playback, THEN THE Client SHALL immediately stop playback
2. THE Client SHALL send an interrupt JSON message to the Server
3. WHEN the Server receives an interrupt message, THEN THE Server SHALL set an interrupt event flag
4. THE Server SHALL drain all pipeline queues (transcript, token, audio) when interrupt is triggered
5. THE Server SHALL reset pipeline state to "listening" after interrupt handling
6. THE Server SHALL send a status update to the Client indicating "listening" state
7. THE Server SHALL clear the interrupt event flag after handling completes

### Requirement 13: Keyboard Text Input

**User Story:** As a kiosk user, I want to type questions using a keyboard or on-screen keyboard, so that I can interact with the system in noisy environments or when voice input is inconvenient.

#### Acceptance Criteria

1. THE Client SHALL capture keyboard input from physical keyboard or on-screen keyboard widget
2. WHEN the user presses Enter or clicks a submit button, THEN THE Client SHALL send a text_input JSON message to the Server
3. THE text_input message SHALL include the text content and language hint ("auto", "en", or "ja")
4. THE Client SHALL validate that text input is non-empty before sending
5. THE Client SHALL limit text input to 1000 characters maximum
6. THE Client SHALL clear the input field after successful submission
7. THE Server SHALL process keyboard text input through the same pipeline as voice input (RAG → LLM → TTS)

### Requirement 14: User Interface Display

**User Story:** As a kiosk user, I want to see a clear visual interface showing conversation history and system status, so that I can understand what the system is doing.

#### Acceptance Criteria

1. THE Client SHALL display a fullscreen PyQt6 window in kiosk mode with no window chrome
2. THE Client SHALL display a conversation transcript showing user queries and system responses
3. THE Client SHALL display a status indicator with three states: Listening (🟢), Thinking (🟡), Speaking (🔵)
4. WHEN the Server sends a transcript event, THEN THE Client SHALL display the recognized user speech
5. WHEN the Server sends llm_text_chunk events, THEN THE Client SHALL display the system response text incrementally
6. THE Client SHALL provide an on-screen keyboard widget for text input (optional, can be disabled)
7. THE Client SHALL apply Qt stylesheets for consistent visual appearance

### Requirement 15: Session Management

**User Story:** As a system operator, I want each kiosk session to be properly initialized and tracked, so that I can monitor usage and troubleshoot issues.

#### Acceptance Criteria

1. THE Client SHALL send a session_start message immediately after WebSocket connection
2. THE session_start message SHALL include a unique kiosk_id identifier
3. THE session_start message SHALL include the kiosk's physical location
4. THE Server SHALL maintain conversation history for each active session
5. THE Server SHALL limit conversation history to the last 10 turns to prevent memory growth
6. THE Server SHALL clear conversation history when the WebSocket connection closes
7. THE Server SHALL log session start and end events with kiosk_id for audit purposes

### Requirement 16: Error Handling and Reporting

**User Story:** As a kiosk user, I want to receive clear error messages when the system encounters problems, so that I know what went wrong and what to do next.

#### Acceptance Criteria

1. WHEN any component fails, THEN THE Server SHALL send an error event to the Client
2. THE error event SHALL include an error code and human-readable message
3. THE Client SHALL display error messages in the UI
4. WHEN all LLM backends fail, THEN THE Server SHALL send error code "llm_unavailable"
5. WHEN STT fails, THEN THE Server SHALL send error code "stt_failed"
6. WHEN TTS fails, THEN THE Server SHALL send error code "tts_failed" and optionally send text-only response
7. THE Server SHALL log all errors with timestamps and context for debugging

### Requirement 17: Performance and Latency

**User Story:** As a kiosk user, I want fast responses to my questions, so that the interaction feels natural and conversational.

#### Acceptance Criteria

1. THE System SHALL achieve <600ms Time-to-First-Audio (TTFA) under normal conditions
2. THE Server SHALL complete STT transcription within 150ms for typical utterances
3. THE Server SHALL complete RAG retrieval within 30ms for typical queries
4. THE Server SHALL generate the first LLM token within 200ms (vLLM backend)
5. THE Server SHALL synthesize the first TTS sentence within 150ms
6. THE Server SHALL execute STT and RAG in parallel to minimize total latency
7. THE Server SHALL stream TTS audio sentence-by-sentence rather than waiting for complete LLM response

### Requirement 18: Bilingual Support

**User Story:** As a bilingual building occupant, I want to interact with the system in either English or Japanese, so that I can use my preferred language.

#### Acceptance Criteria

1. THE System SHALL support English and Japanese languages for all interactions
2. THE System SHALL automatically detect the language of each user input
3. THE System SHALL respond in the same language as the user query
4. THE System SHALL use language-specific TTS engines (CosyVoice2 for English, VOICEVOX for Japanese)
5. THE System SHALL filter RAG results by detected language to return relevant documents
6. THE System SHALL use language-specific text cleaning rules (different filler words for EN/JP)
7. THE System SHALL use polite form (です・ます体) for Japanese responses

### Requirement 19: Web Search Tool Integration

**User Story:** As a kiosk user, I want the system to search the web for current information not in the building directory, so that I can get answers to questions beyond building navigation.

#### Acceptance Criteria

1. THE Server SHALL provide a web_search tool function to the LLM
2. THE LLM SHALL be able to call the web_search tool when building knowledge is insufficient
3. THE Server SHALL use self-hosted SearXNG service for web searches
4. THE Server SHALL send search queries to SearXNG at http://searxng:8080/search
5. THE Server SHALL return the top 3 search results to the LLM
6. THE Server SHALL include result titles and content snippets in the tool response
7. THE Server SHALL set a 5-second timeout for web search requests

### Requirement 20: Docker Deployment

**User Story:** As a system administrator, I want to deploy the server components using Docker Compose, so that I can easily manage dependencies and scaling.

#### Acceptance Criteria

1. THE Server SHALL be deployable via Docker Compose
2. THE Docker Compose stack SHALL include services for: voice-server, vLLM, Ollama, VOICEVOX, SearXNG
3. THE voice-server container SHALL have access to GPU via NVIDIA Container Toolkit
4. THE vLLM container SHALL run Qwen2.5-7B-Instruct model with AWQ quantization
5. THE VOICEVOX container SHALL expose REST API on port 50021
6. THE SearXNG container SHALL expose search API on port 8080
7. THE Docker Compose stack SHALL mount model weights from host filesystem
8. THE Docker Compose stack SHALL mount building knowledge base from host filesystem
9. THE Docker Compose stack SHALL persist ChromaDB data across container restarts

### Requirement 21: Client System Service

**User Story:** As a system administrator, I want the kiosk client to start automatically on boot, so that the kiosk is always ready for user interaction.

#### Acceptance Criteria

1. THE Client SHALL be deployable as a systemd service on Ubuntu 22.04
2. THE systemd service SHALL start after graphical.target, network-online.target, and sound.target
3. THE systemd service SHALL run as a dedicated "kiosk" user account
4. THE systemd service SHALL set DISPLAY=:0 environment variable for GUI display
5. THE systemd service SHALL automatically restart on failure with 3-second delay
6. THE systemd service SHALL log output to systemd journal
7. THE systemd service SHALL be enabled to start on boot

### Requirement 22: Configuration Management

**User Story:** As a system administrator, I want to configure system behavior through environment variables, so that I can customize deployments without code changes.

#### Acceptance Criteria

1. THE Server SHALL read configuration from environment variables
2. THE Server SHALL support configuration for: VLLM_BASE_URL, VLLM_MODEL_NAME, OLLAMA_BASE_URL, OLLAMA_MODEL_NAME, GROK_API_KEY
3. THE Server SHALL support configuration for: STT_MODEL, STT_COMPUTE_TYPE, TTS_EN_ENGINE, TTS_JP_URL
4. THE Server SHALL support configuration for: CHROMADB_PATH, BUILDING_NAME
5. THE Client SHALL read SERVER_WS_URL, KIOSK_ID, and KIOSK_LOCATION from environment variables
6. THE System SHALL provide an .env.example file documenting all configuration options
7. WHEN required configuration is missing, THEN THE System SHALL log an error and fail to start

### Requirement 23: Health Monitoring

**User Story:** As a system administrator, I want to monitor the health of system components, so that I can detect and resolve issues proactively.

#### Acceptance Criteria

1. THE Server SHALL expose a /health HTTP endpoint for health checks
2. THE Server SHALL perform health checks on all LLM backends before use
3. THE Server SHALL perform health checks on TTS engines before synthesis
4. THE health check endpoint SHALL return HTTP 200 when all critical components are healthy
5. THE health check endpoint SHALL return HTTP 503 when critical components are unhealthy
6. THE Docker Compose stack SHALL configure health checks for the voice-server container
7. THE health checks SHALL run every 30 seconds with 10-second timeout and 3 retries

### Requirement 24: Resource Management

**User Story:** As a system administrator, I want the system to use GPU resources efficiently, so that I can run all components on a single GPU server.

#### Acceptance Criteria

1. THE Server SHALL require 12-16GB VRAM for all AI models combined
2. THE vLLM service SHALL use up to 90% of available GPU memory
3. THE STT service SHALL use float16 precision on GPUs with ≥12GB VRAM
4. THE STT service SHALL use int8 precision on GPUs with <12GB VRAM
5. THE TTS service SHALL allocate ~1GB VRAM for CosyVoice2 model
6. THE RAG embedder SHALL run on CPU to offload GPU
7. THE System SHALL use separate CUDA streams for STT, LLM, and TTS to prevent blocking

### Requirement 25: Security and Privacy

**User Story:** As a building occupant, I want my voice interactions to remain private and secure, so that my personal information is protected.

#### Acceptance Criteria

1. THE System SHALL operate entirely on a private network (no internet access except Grok fallback)
2. THE System SHALL validate all WebSocket messages against schema before processing
3. THE System SHALL limit audio input to 30 seconds maximum to prevent memory exhaustion
4. THE System SHALL limit text input to 1000 characters maximum
5. THE System SHALL implement rate limiting of 10 requests per minute per kiosk
6. THE System SHALL store conversation history in memory only (not persisted to disk)
7. THE System SHALL clear conversation history when WebSocket connection closes
8. THE System SHALL log a warning when Grok API is used (data leaves local network)
9. THE System SHALL optionally support WSS (WebSocket Secure) for encrypted transport

### Requirement 26: Audio Format and Encoding

**User Story:** As a system, I want to use efficient audio encoding for network transmission, so that bandwidth usage is minimized without sacrificing quality.

#### Acceptance Criteria

1. THE Client SHALL send audio upstream as raw PCM16 binary frames (16kHz, mono)
2. THE Server SHALL send audio downstream as Opus-encoded binary frames (48kHz, mono)
3. THE Opus encoder SHALL use VOIP application mode for speech optimization
4. THE Opus encoder SHALL use 20ms frame size (960 samples at 48kHz)
5. THE Client SHALL decode Opus frames to PCM16 for playback
6. THE Opus encoding SHALL reduce bandwidth by ~80% compared to raw PCM16
7. THE Opus encoding SHALL maintain transparent quality at 64kbps for speech

### Requirement 27: Knowledge Base Ingestion

**User Story:** As a system administrator, I want to ingest building knowledge documents into the RAG system, so that the chatbot can answer questions about the building.

#### Acceptance Criteria

1. THE System SHALL provide a knowledge base ingestion script
2. THE ingestion script SHALL read markdown documents from the building_kb/ directory
3. THE ingestion script SHALL chunk documents into appropriate sizes for embedding
4. THE ingestion script SHALL extract metadata (language, floor, type) from document structure
5. THE ingestion script SHALL generate embeddings using multilingual-e5-large model
6. THE ingestion script SHALL store document chunks and embeddings in ChromaDB
7. THE ingestion script SHALL support both English and Japanese documents
8. THE ingestion script SHALL be idempotent (can be run multiple times safely)

### Requirement 28: Model Management

**User Story:** As a system administrator, I want to download and manage AI model weights, so that the system has all required models available.

#### Acceptance Criteria

1. THE System SHALL provide a model download script
2. THE download script SHALL download Whisper Large V3 Turbo weights
3. THE download script SHALL download multilingual-e5-large weights
4. THE download script SHALL download CosyVoice2-0.5B weights
5. THE download script SHALL download Qwen2.5-7B-Instruct weights for vLLM
6. THE download script SHALL store model weights in the models/ directory
7. THE models/ directory SHALL be mounted read-only in Docker containers
8. THE System SHALL verify model integrity after download

### Requirement 29: Logging and Debugging

**User Story:** As a system administrator, I want comprehensive logging of system operations, so that I can troubleshoot issues and monitor performance.

#### Acceptance Criteria

1. THE Server SHALL log all WebSocket connections and disconnections
2. THE Server SHALL log all STT transcriptions with language and confidence
3. THE Server SHALL log all LLM backend health checks and failovers
4. THE Server SHALL log all TTS synthesis requests and durations
5. THE Server SHALL log all errors with full stack traces
6. THE Client SHALL log all VAD events (speech_start, speech_end)
7. THE Client SHALL log all WebSocket reconnection attempts
8. THE System SHALL use structured logging with timestamps and log levels
9. THE System SHALL support configurable log levels (DEBUG, INFO, WARNING, ERROR)

### Requirement 30: Graceful Degradation

**User Story:** As a kiosk user, I want the system to continue functioning even when some components fail, so that I can still get assistance.

#### Acceptance Criteria

1. WHEN vLLM fails, THEN THE System SHALL automatically fall back to Ollama
2. WHEN Ollama fails, THEN THE System SHALL automatically fall back to Grok API
3. WHEN VOICEVOX fails, THEN THE System SHALL fall back to Fish Speech for Japanese TTS
4. WHEN all TTS engines fail, THEN THE System SHALL send text-only responses to the Client
5. WHEN RAG retrieval fails, THEN THE System SHALL proceed with LLM inference without context
6. WHEN web search fails, THEN THE System SHALL inform the LLM that search is unavailable
7. THE System SHALL log all fallback events for monitoring and alerting
