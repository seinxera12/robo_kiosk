"""
Pipeline state management and orchestration for voice chatbot.

This module defines the PipelineState dataclass that manages shared state
across pipeline workers and the VoicePipeline class that orchestrates
the entire voice processing pipeline.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional, Any
import torch

import logging

logger = logging.getLogger(__name__)



@dataclass
class PipelineState:
    """
    Shared state for pipeline workers.
    
    This dataclass maintains the state for processing voice interactions through
    the pipeline, including queues for data flow between stages, interrupt handling
    for barge-in support, conversation history, and status tracking.
    
    Attributes:
        audio_input: Queue for incoming audio frames from client
        transcript: Queue for transcription results from STT
        token: Queue for LLM token stream
        audio_output: Queue for synthesized audio chunks to send to client
        interrupt_event: Event flag for handling user barge-in interrupts
        conversation_history: List of recent conversation turns (max 10)
        status: Current pipeline status (listening/thinking/speaking/idle)
        current_turn: Current conversation turn metadata
    
    Invariants:
        - Only one turn active at a time
        - Interrupt event cleared between turns
        - Queues drained on interrupt
        - conversation_history never exceeds 10 turns
    
    Requirements:
        - 15.4: Maintains conversation history for each active session
        - 15.5: Limits conversation history to last 10 turns
        - 15.6: Conversation history cleared when connection closes
    """
    
    # Queues for pipeline data flow
    audio_input: asyncio.Queue = field(default_factory=asyncio.Queue)
    transcript: asyncio.Queue = field(default_factory=asyncio.Queue)
    token: asyncio.Queue = field(default_factory=asyncio.Queue)
    audio_output: asyncio.Queue = field(default_factory=asyncio.Queue)
    
    # Interrupt handling for barge-in
    interrupt_event: asyncio.Event = field(default_factory=asyncio.Event)
    
    # Conversation history (max 10 turns)
    conversation_history: list = field(default_factory=list)
    
    # Status tracking
    status: str = "idle"
    
    # Current turn metadata
    current_turn: Optional[dict] = None


class VoicePipeline:
    """
    Main pipeline orchestrator for voice chatbot.
    
    This class manages the entire voice processing pipeline, coordinating
    multiple async worker coroutines that handle STT, LLM inference, TTS,
    and WebSocket communication.
    
    Preconditions:
        - WebSocket connection established
        - Config object provided with all required settings
    
    Postconditions:
        - Processes voice turns until disconnect
        - Handles interrupts gracefully
        - Cleans up resources on exit
    
    Requirements:
        - 3.1: Establishes persistent WebSocket connection
        - 3.2: Sends binary PCM16 audio frames upstream
        - 3.3: Sends JSON control messages upstream
        - 3.4: Receives binary Opus-encoded audio frames downstream
        - 3.5: Receives JSON event messages downstream
    """
    
    def __init__(self, websocket: Any, config: Any, stt=None, llm_chain=None, rag=None, tts_router=None):
        """
        Initialize the voice pipeline.

        Args:
            websocket:  Active WebSocket connection
            config:     Config object
            stt:        Pre-loaded WhisperSTT instance
            llm_chain:  Pre-loaded LLMFallbackChain instance
            rag:        Pre-loaded BuildingKB instance
            tts_router: Pre-loaded TTSRouter instance
        """
        self.ws = websocket
        self.config = config

        # Use pre-loaded components (fast path) or construct them (slow path)
        if stt is not None:
            self.stt = stt
        else:
            from server.stt.whisper_stt import WhisperSTT
            self.stt = WhisperSTT(
                model_size=config.stt_model,
                device=config.stt_device,
                compute_type=config.stt_compute_type
            )

        if llm_chain is not None:
            self.llm_chain = llm_chain
        else:
            from server.llm.fallback_chain import LLMFallbackChain
            self.llm_chain = LLMFallbackChain(config)

        if rag is not None:
            self.rag = rag
        else:
            from server.rag.chroma_store import BuildingKB
            self.rag = BuildingKB(config.chromadb_path)

        if tts_router is not None:
            self.tts_router = tts_router
        else:
            from server.tts.tts_router import TTSRouter
            self.tts_router = TTSRouter(config)

        self.state = PipelineState()

        # Intent classifier — reuses the RAG embedder (no extra model load)
        from server.llm.intent_classifier import IntentClassifier
        self.intent_classifier = IntentClassifier(
            embedder=self.rag.embedder if self.rag is not None else None
        )

        logger.info("VoicePipeline initialized")
    
    async def run(self) -> None:
        """
        Main pipeline loop that launches all worker coroutines.
        
        This method starts all worker tasks concurrently using asyncio.gather
        and ensures proper cleanup on exit.
        
        Preconditions:
            - WebSocket connected
            - All components initialized
        
        Postconditions:
            - Runs until disconnect or error
            - Cleans up resources on exit
            - All worker tasks are properly terminated
        
        Loop Invariants:
            - State remains consistent across turns
            - Interrupt event checked each iteration
        
        Requirements:
            - 3.1: Persistent WebSocket connection handling
            - 3.2: Binary audio frame processing
            - 3.3: JSON control message handling
        """
        logger.info("Starting VoicePipeline workers")
        
        try:
            # Start all worker tasks concurrently
            workers = await asyncio.gather(
                self.audio_input_worker(),
                self.llm_worker(),
                self.tts_worker(),
                self.audio_output_worker(),  # NEW: Send TTS audio to client
                self.websocket_receiver(),
                return_exceptions=True
            )
            
            # Log any exceptions from workers
            for i, result in enumerate(workers):
                if isinstance(result, Exception):
                    logger.error(f"Worker {i} failed with exception: {result}")
        
        except Exception as e:
            logger.error(f"Pipeline error: {e}", exc_info=True)
            raise
        
        finally:
            await self.cleanup()
    
    async def audio_input_worker(self) -> None:
        """
        Process incoming audio frames and perform STT transcription.
        
        This worker continuously processes audio frames from the audio_input queue,
        transcribes them using STT, and puts the results in the transcript queue.
        
        Preconditions:
            - audio_input queue receives PCM16 audio bytes
            - STT component is initialized
        
        Postconditions:
            - Transcription results placed in transcript queue
            - Handles interrupt events gracefully
        
        Loop Invariants:
            - Checks interrupt_event on each iteration
            - Processes one audio frame at a time
        
        Requirements:
            - 3.2: Receives binary PCM16 audio frames
            - 4.1: Transcribes audio using Whisper
            - 4.2: Uses greedy decoding for minimum latency
        """
        logger.info("audio_input_worker started")
        
        while True:
            try:
                # Check for interrupt
                if self.state.interrupt_event.is_set():
                    await asyncio.sleep(0.1)
                    continue
                
                # Get audio bytes from queue
                audio_bytes = await self.state.audio_input.get()
                logger.debug(f"Received audio bytes: {len(audio_bytes)} bytes")

                # STT-BUG-004: guard against very short audio that causes Whisper
                # to return empty or hallucinated text, wasting an LLM call.
                # 16000 bytes = 8000 samples = 0.5s at 16kHz PCM16.
                MIN_AUDIO_BYTES = 16000
                if len(audio_bytes) < MIN_AUDIO_BYTES:
                    logger.warning(
                        f"Audio too short ({len(audio_bytes)} bytes), skipping STT"
                    )
                    self.state.audio_input.task_done()
                    continue

                # Transcribe audio using STT
                result = await self.stt.transcribe(audio_bytes)

                # Update current turn language so tts_worker routes correctly
                self.state.current_turn = {"lang": result.language}

                await self.state.transcript.put(result)

                # Send transcript back to client so UI can show what was heard
                await self.ws.send_json({
                    "type": "transcript",
                    "text": result.text,
                    "lang": result.language,
                    "final": True
                })
                
                logger.info(f"Transcribed: {result.text[:50]}... (lang={result.language})")
                
                # Mark task as done
                self.state.audio_input.task_done()
            
            except asyncio.CancelledError:
                logger.info("audio_input_worker cancelled")
                break
            
            except Exception as e:
                logger.error(f"Error in audio_input_worker: {e}", exc_info=True)
                # Continue processing despite errors
    
    async def llm_worker(self) -> None:
        """
        Process transcripts and generate LLM responses with RAG.
        
        This worker retrieves transcripts, performs RAG retrieval in parallel,
        builds prompts, and streams LLM tokens to the token queue.
        
        Preconditions:
            - transcript queue receives TranscriptionResult objects
            - RAG and LLM components are initialized
        
        Postconditions:
            - LLM tokens placed in token queue
            - RAG context retrieved and included in prompt
            - Conversation history updated
        
        Loop Invariants:
            - Checks interrupt_event on each iteration
            - Processes one transcript at a time
            - Conversation history never exceeds 10 turns
        
        Requirements:
            - 7.3: Retrieves top-3 most relevant document chunks
            - 7.5: Launches RAG retrieval in parallel
            - 8.1: Attempts LLM inference using fallback chain
            - 8.7: Streams LLM tokens as generated
            - 9.1: Constructs LLM prompts with context
        """
        logger.info("llm_worker started")
        
        while True:
            try:
                # Check for interrupt
                if self.state.interrupt_event.is_set():
                    await asyncio.sleep(0.1)
                    continue
                
                # Get transcript from queue
                transcript = await self.state.transcript.get()
                logger.debug(f"Received transcript: {transcript}")
                
                # Classify intent to decide context source and system prompt
                from server.llm.intent_classifier import Intent
                intent_result = self.intent_classifier.classify(
                    transcript.text,
                    history=self.state.conversation_history,
                )
                intent = intent_result.intent
                logger.info(
                    f"Intent: {intent.value} "
                    f"(conf={intent_result.confidence:.2f}, method={intent_result.method})"
                )

                # Fetch context based on intent
                context = ""
                if intent == Intent.BUILDING and self.config.use_rag:
                    context = await self.rag.retrieve(
                        query=transcript.text,
                        lang=transcript.language,
                        n=3,
                    )
                    logger.info(f"RAG context: {len(context)} chars")

                elif intent == Intent.SEARCH:
                    try:
                        from server.search.searxng_client import searxng_search
                        from server.llm.prompt_builder import format_search_context
                        results = await searxng_search(
                            query=transcript.text,
                            base_url=self.config.searxng_url,
                            n_results=3,
                            lang=transcript.language,
                        )
                        logger.info(f"Search returned {len(results)} results for query: '{transcript.text}'")
                        
                        # Log detailed search results
                        for i, result in enumerate(results):
                            title = result.get('title', 'No title')
                            content = result.get('content', 'No content')
                            url = result.get('url', 'No URL')
                            logger.info(f"Search result {i+1}:")
                            logger.info(f"  Title: {title}")
                            logger.info(f"  Content: {content[:300]}{'...' if len(content) > 300 else ''}")
                            logger.info(f"  URL: {url}")
                        
                        context = format_search_context(results)
                        if context:
                            logger.info(f"Formatted search context: {len(context)} characters")
                            logger.info(f"Search context content:\n{context}")
                        else:
                            logger.warning("Search returned no usable results — falling back to GENERAL")
                            intent = Intent.GENERAL
                    except Exception as e:
                        logger.warning(f"Search failed ({e}) — falling back to GENERAL")
                        intent = Intent.GENERAL

                # Build prompt with intent-specific system prompt + context
                from server.llm.prompt_builder import build_messages
                messages = build_messages(
                    user_text=transcript.text,
                    lang=transcript.language,
                    context=context,
                    history=self.state.conversation_history,
                    kiosk_meta={
                        "building_name": self.config.building_name,
                        "location": "kiosk",
                    },
                    building_name=self.config.building_name,
                    intent=intent,
                )

                logger.info(f"Prompt built: intent={intent.value}, messages={len(messages)}")
                
                # Log the final prompt for debugging
                logger.info("=== FINAL PROMPT TO LLM ===")
                for i, msg in enumerate(messages):
                    role = msg.get('role', 'unknown')
                    content = msg.get('content', '')
                    logger.info(f"Message {i+1} ({role}):")
                    logger.info(f"{content}")
                    logger.info("---")
                logger.info("=== END PROMPT ===")
                
                # Stream LLM response with fallback — collect full response for history
                full_response = ""
                async for token in self.llm_chain.stream_with_fallback(messages):
                    full_response += token
                    await self.state.token.put(token)
                    await self.ws.send_json({
                        "type": "llm_text_chunk",
                        "text": token,
                        "final": False
                    })

                # Signal end of response
                await self.ws.send_json({"type": "llm_text_chunk", "text": "", "final": True})
                logger.info("LLM streaming complete")

                # Update conversation history with this turn.
                # Store the detected language alongside each entry so the
                # prompt builder can strip out any cross-language contamination.
                self.state.conversation_history.append(
                    {"role": "user", "content": transcript.text, "lang": transcript.language}
                )
                self.state.conversation_history.append(
                    {"role": "assistant", "content": full_response, "lang": transcript.language}
                )
                # Keep last 10 turns (20 messages = 10 user + 10 assistant)
                if len(self.state.conversation_history) > 20:
                    self.state.conversation_history = self.state.conversation_history[-20:]

                logger.info(f"History updated: {len(self.state.conversation_history)} messages")
                
                # Mark task as done
                self.state.transcript.task_done()
            
            except asyncio.CancelledError:
                logger.info("llm_worker cancelled")
                break
            
            except Exception as e:
                logger.error(f"Error in llm_worker: {e}", exc_info=True)
                # Continue processing despite errors
    
    async def tts_worker(self) -> None:
        """
        Synthesize TTS from token stream with sentence-boundary streaming.
        
        This worker collects tokens until a sentence boundary is detected,
        then synthesizes the complete sentence and streams audio chunks.
        
        Preconditions:
            - token queue receives string tokens from LLM
            - TTS router is initialized
        
        Postconditions:
            - Audio chunks placed in audio_output queue
            - Sentences synthesized as they complete
            - Remaining buffer flushed after LLM completes
        
        Loop Invariants:
            - Checks interrupt_event on each iteration
            - Buffer contains only incomplete sentence fragments
            - All complete sentences are synthesized
        
        Requirements:
            - 10.4: Synthesizes audio sentence-by-sentence
            - 10.5: Detects sentence boundaries (.?!。？！…)
            - 10.6: Streams audio chunks as generated
            - 10.7: Flushes remaining buffer after LLM completes
        """
        logger.info("tts_worker started")
        
        SENTENCE_ENDINGS = frozenset('.?!。？！…')
        
        while True:
            try:
                # Check for interrupt
                if self.state.interrupt_event.is_set():
                    await asyncio.sleep(0.1)
                    continue
                
                # Determine current language for language-aware sentence detection
                current_lang = "en"
                if self.state.current_turn and "lang" in self.state.current_turn:
                    current_lang = self.state.current_turn["lang"]
                
                # Use shorter minimum for Japanese (2 chars) vs English (8 chars)
                min_sentence_length = 2 if current_lang == "ja" else 8
                
                # Collect tokens until sentence boundary.
                # Drain already-queued tokens first (non-blocking) to avoid
                # accumulating a huge backlog into one chunk while TTS is busy.
                buffer = ""
                sentence_complete = False

                while not sentence_complete:
                    # Drain whatever is already queued without blocking
                    while not self.state.token.empty():
                        try:
                            token = self.state.token.get_nowait()
                            self.state.token.task_done()
                            buffer += token
                            if (buffer and
                                    buffer[-1] in SENTENCE_ENDINGS and
                                    len(buffer) >= min_sentence_length):
                                sentence_complete = True
                                break
                        except asyncio.QueueEmpty:
                            break

                    if sentence_complete:
                        break

                    # Wait briefly for the next token
                    try:
                        token = await asyncio.wait_for(
                            self.state.token.get(),
                            timeout=0.3
                        )
                        self.state.token.task_done()
                        buffer += token

                        if (buffer and
                                buffer[-1] in SENTENCE_ENDINGS and
                                len(buffer) >= min_sentence_length):
                            sentence_complete = True

                    except asyncio.TimeoutError:
                        # No new tokens — flush whatever we have
                        if buffer.strip():
                            sentence_complete = True
                        # else keep waiting
                
                if not buffer.strip():
                    continue
                
                logger.debug(f"Complete sentence detected: {buffer[:50]}...")
                
                # Get TTS engine for current language with better detection
                if self.state.current_turn and "lang" in self.state.current_turn:
                    current_lang = self.state.current_turn["lang"]
                else:
                    # If no language is set, detect from the buffer text
                    from server.lang.detector import detect_language
                    current_lang = detect_language(buffer)
                    logger.debug(f"No language set, detected from text: {current_lang}")
                
                # Ensure we only use supported languages
                if current_lang not in ["en", "ja"]:
                    logger.warning(f"Unsupported language '{current_lang}', defaulting to English")
                    current_lang = "en"
                
                logger.info(f"TTS synthesis for language: {current_lang}")
                tts_engine = self.tts_router.get_engine(lang=current_lang)
                
                if tts_engine is None:
                    logger.warning(f"No TTS engine available for language: {current_lang}")
                    continue
                
                # Fire synthesis as a background task so the tts_worker loop
                # immediately returns to collecting the next sentence's tokens.
                # This pipelines synthesis of sentence N+1 with playback of N.
                async def _synthesize_and_queue(text: str, engine) -> None:
                    try:
                        async for audio_chunk in engine.synthesize_stream(text):
                            # Abort immediately if an interrupt arrived
                            if self.state.interrupt_event.is_set():
                                logger.info("TTS synthesis aborted by interrupt")
                                return
                            if audio_chunk:
                                await self.state.audio_output.put(audio_chunk)
                                logger.debug(f"Queued {len(audio_chunk)} bytes of audio")
                    except asyncio.CancelledError:
                        logger.info("TTS synthesis task cancelled")
                    except Exception as exc:
                        logger.error(f"TTS synthesis error: {exc}", exc_info=True)
                    logger.info("TTS synthesis complete for sentence")

                asyncio.create_task(_synthesize_and_queue(buffer, tts_engine))

            except asyncio.CancelledError:
                logger.info("tts_worker cancelled")
                break
            
            except Exception as e:
                logger.error(f"Error in tts_worker: {e}", exc_info=True)
                # Continue processing despite errors
    
    async def audio_output_worker(self) -> None:
        """
        Send synthesized audio to client via WebSocket.
        
        This worker consumes audio chunks from the audio_output queue
        and sends them to the client as binary WebSocket messages.
        
        Preconditions:
            - audio_output queue receives WAV audio bytes from TTS
            - WebSocket connection is active
        
        Postconditions:
            - All audio chunks sent to client
            - Client receives audio for playback
        
        Loop Invariants:
            - Checks interrupt_event on each iteration
            - Processes one audio chunk at a time
        
        Requirements:
            - 3.4: Sends binary audio frames downstream
            - 10.6: Streams audio chunks as generated
        """
        logger.info("audio_output_worker started")
        
        while True:
            try:
                # Check for interrupt
                if self.state.interrupt_event.is_set():
                    await asyncio.sleep(0.1)
                    continue
                
                # Get audio chunk from queue
                audio_chunk = await self.state.audio_output.get()
                
                if not audio_chunk:
                    logger.warning("Empty audio chunk received, skipping")
                    self.state.audio_output.task_done()
                    continue
                
                logger.debug(f"Sending {len(audio_chunk)} bytes of audio to client")
                
                # Send audio to client as binary WebSocket message
                try:
                    await self.ws.send_bytes(audio_chunk)
                    logger.debug("Audio chunk sent successfully")
                except Exception as e:
                    logger.error(f"Failed to send audio to client: {e}")
                
                # Mark task as done
                self.state.audio_output.task_done()
            
            except asyncio.CancelledError:
                logger.info("audio_output_worker cancelled")
                break
            
            except Exception as e:
                logger.error(f"Error in audio_output_worker: {e}", exc_info=True)
                # Continue processing despite errors
    
    async def websocket_receiver(self) -> None:
        logger.info("websocket_receiver started")
        
        while True:
            try:
                message = await self.ws.receive()
                
                # Handle WebSocket disconnect
                if message.get("type") == "websocket.disconnect":
                    logger.info("WebSocket disconnected")
                    break
                
                # Handle binary audio frames
                if "bytes" in message:
                    audio_data = message["bytes"]
                    # Interrupt any in-flight TTS before queuing new audio input
                    if self.state.interrupt_event.is_set() is False:
                        await self.handle_interrupt(notify_client=False)
                    await self.state.audio_input.put(audio_data)
                
                # Handle JSON control messages
                elif "text" in message:
                    import json
                    control_msg = json.loads(message["text"])
                    await self.handle_control_message(control_msg)
            
            except asyncio.CancelledError:
                logger.info("websocket_receiver cancelled")
                break
            
            except RuntimeError as e:
                if "disconnect" in str(e).lower():
                    logger.info("WebSocket connection closed")
                else:
                    logger.error(f"WebSocket runtime error: {e}")
                break  # always stop on RuntimeError from receive()
            
            except Exception as e:
                logger.error(f"Error in websocket_receiver: {e}", exc_info=True)
                break  # stop the loop on any unexpected error
    
    async def handle_control_message(self, message: dict) -> None:
        """Handle JSON control messages from client."""
        msg_type = message.get("type")
        
        if msg_type == "interrupt":
            await self.handle_interrupt()
        elif msg_type == "session_start":
            kiosk_id = message.get("kiosk_id", "unknown")
            kiosk_location = message.get("kiosk_location", "unknown")
            # Don't set a default language - let it be detected per message
            self.state.current_turn = {}
            logger.info(f"Session started: kiosk_id={kiosk_id}, location={kiosk_location}")
            await self.ws.send_json({"type": "session_ack", "status": "ready"})
        elif msg_type == "text_input":
            text = message.get("text", "")
            lang = message.get("lang", "auto")

            # Always re-detect language server-side from the actual text content.
            # Never trust the client's lang field — it may be stale, hardcoded,
            # or wrong for mixed-script queries like "TYO株の最新価格はいくらですか？".
            from server.lang.detector import detect_language
            detected_lang = detect_language(text)

            # Only use the client-supplied lang if it is an explicit, valid code
            # AND the server detection agrees (or the text is too short to be sure).
            if lang in ("en", "ja") and len(text) >= 4:
                # If server detection disagrees with client, trust the server.
                if detected_lang != lang:
                    logger.info(
                        f"Language override: client said '{lang}', "
                        f"server detected '{detected_lang}' — using server detection"
                    )
                lang = detected_lang
            else:
                lang = detected_lang

            logger.info(f"Text input received: {text[:50]}... (lang={lang})")
            logger.debug(f"Full text for language detection: '{text}'")

            # Interrupt any in-flight TTS synthesis tasks and drain queues
            # so the new response starts cleanly without leftover audio.
            await self.handle_interrupt(notify_client=False)

            # Set current turn language so tts_worker picks the right engine
            self.state.current_turn = {"lang": lang}
            # Build a transcript-like object and push it directly into the transcript queue
            from types import SimpleNamespace
            transcript = SimpleNamespace(text=text, language=lang)
            await self.state.transcript.put(transcript)
        else:
            logger.warning(f"Unknown control message type: {msg_type}")
    
    async def handle_interrupt(self, notify_client: bool = True) -> None:
        """
        Handle user interrupt (barge-in) during TTS playback.
        
        This method handles user barge-in interrupts by signaling all workers
        to abort, draining all pipeline queues, resetting state, and notifying
        the client.
        
        Preconditions:
            - Pipeline is in active processing state
            - interrupt_event is an asyncio.Event instance
        
        Postconditions:
            - All pipeline queues are drained
            - Pipeline state is reset to "listening"
            - interrupt_event is set
            - Client receives status update
        
        Loop Invariants:
            - All queue items processed so far are discarded
            - Pipeline workers check interrupt_event on each iteration
        
        Requirements:
            - 12.3: Sets interrupt event flag when interrupt received
            - 12.4: Drains all pipeline queues when interrupt triggered
            - 12.5: Resets pipeline state to "listening" after interrupt
            - 12.6: Sends status update to client indicating "listening" state
            - 12.7: Clears interrupt event flag after handling completes
        """
        logger.info("Handling barge-in interrupt")
        
        # Signal all workers to abort
        self.state.interrupt_event.set()

        # Yield to the event loop so any in-flight background tasks
        # (_synthesize_and_queue) get a chance to see interrupt_event
        # and exit before we drain the queues.
        await asyncio.sleep(0)
        
        # Drain all queues
        await self._drain_queue(self.state.audio_input)
        await self._drain_queue(self.state.transcript)
        await self._drain_queue(self.state.token)
        await self._drain_queue(self.state.audio_output)
        
        # Reset state
        self.state.current_turn = None
        self.state.status = "listening"
        
        # Notify client
        if notify_client:
            await self.ws.send_json({
                "type": "status",
                "state": "listening"
            })
            logger.info("Status update sent to client: listening")
        
        # Clear interrupt flag for next turn
        self.state.interrupt_event.clear()
        
        logger.info("Barge-in interrupt handling complete")
    
    async def _drain_queue(self, queue: asyncio.Queue) -> None:
        """
        Drain all items from an asyncio queue.
        
        This helper method removes all items from a queue without processing them,
        ensuring the queue is empty and all tasks are marked as done.
        
        Preconditions:
            - queue is a valid asyncio.Queue instance
        
        Postconditions:
            - Queue is empty
            - All queued tasks are marked as done
            - No items are lost (they are intentionally discarded)
        
        Loop Invariants:
            - Queue size is monotonically decreasing
            - All retrieved items are marked as done
        
        Requirements:
            - 12.4: Drains all pipeline queues when interrupt triggered
        """
        drained_count = 0
        while not queue.empty():
            try:
                queue.get_nowait()
                queue.task_done()
                drained_count += 1
            except asyncio.QueueEmpty:
                break
        
        if drained_count > 0:
            logger.debug(f"Drained {drained_count} items from queue")
    
    async def cleanup(self) -> None:
        """
        Clean up pipeline resources on shutdown.
        
        This method ensures all queues are drained, conversation history
        is cleared, and resources are properly released.
        
        Preconditions:
            - Pipeline is shutting down
        
        Postconditions:
            - All queues are empty
            - Conversation history is cleared
            - Resources are released
        
        Requirements:
            - 15.6: Clears conversation history when connection closes
        """
        logger.info("Cleaning up VoicePipeline")
        
        # Clear conversation history
        self.state.conversation_history.clear()
        
        # Drain all queues using the helper method
        await self._drain_queue(self.state.audio_input)
        await self._drain_queue(self.state.transcript)
        await self._drain_queue(self.state.token)
        await self._drain_queue(self.state.audio_output)
        
        logger.info("VoicePipeline cleanup complete")
