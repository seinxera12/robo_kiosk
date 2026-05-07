"""
FastAPI server for real-time streaming voice chatbot.

Provides WebSocket endpoint for bidirectional audio/text communication
and HTTP health check endpoint.

Requirements: 3.1, 3.7, 23.1, 23.4, 23.5
"""

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from server.config import Config

# Configure logging with UTF-8 support
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
# Ensure UTF-8 encoding for stdout
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

logger = logging.getLogger(__name__)


# Application state
app_state = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.

    Pre-loads all heavy components (Whisper, LLM chain, RAG, TTS) at startup
    so WebSocket connections are accepted instantly without timeout.
    """
    logger.info("Starting voice chatbot server...")
    config = Config.from_env()
    app_state["config"] = config

    # --- Pre-load all heavy components here ---
    logger.info("Pre-loading STT (Whisper)...")
    from server.stt.whisper_stt import WhisperSTT
    app_state["stt"] = WhisperSTT(
        model_size=config.stt_model,
        device=config.stt_device,
        compute_type=config.stt_compute_type
    )

    logger.info("Pre-loading LLM fallback chain...")
    from server.llm.fallback_chain import LLMFallbackChain
    app_state["llm_chain"] = LLMFallbackChain(config)

    logger.info("Pre-loading RAG knowledge base...")
    from server.rag.chroma_store import BuildingKB
    app_state["rag"] = BuildingKB(config.chromadb_path)

    logger.info("Pre-loading TTS router...")
    from server.tts.tts_router import TTSRouter
    app_state["tts_router"] = TTSRouter(config)

    logger.info(f"Server ready -- host={config.host}, port={config.port}")

    yield

    logger.info("Shutting down voice chatbot server...")
    app_state.clear()


# Create FastAPI application
app = FastAPI(
    title="Voice Kiosk Chatbot Server",
    description="Real-time streaming voice chatbot with WebSocket support",
    version="1.0.0",
    lifespan=lifespan
)


# Add CORS middleware (Requirement 3.1)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for kiosk deployment
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    """
    Health check endpoint (Requirements 23.1, 23.4, 23.5).

    Returns HTTP 200 when server is operational.
    Used by Docker health checks and monitoring systems.

    Returns:
        JSONResponse: Health status with server information
    """
    config = app_state.get("config")
    tts_router = app_state.get("tts_router")

    health_status = {
        "status": "healthy",
        "service": "voice-kiosk-chatbot",
        "version": "1.0.0",
    }

    if config:
        health_status["config"] = {
            "building_name": config.building_name,
            "stt_model": config.stt_model,
        }

    # Check TTS engine status
    if tts_router:
        tts_status = {}

        # Kokoro (English)
        if tts_router.kokoro:
            try:
                is_ready = await tts_router.kokoro.health_check()
                tts_status["kokoro_en"] = "ready" if is_ready else "not_loaded"
            except Exception as e:
                tts_status["kokoro_en"] = f"error: {str(e)}"
        else:
            tts_status["kokoro_en"] = "not_initialized"

        # KokoClone (Japanese primary)
        if tts_router.kokoclone:
            try:
                is_ready = await tts_router.kokoclone.health_check()
                tts_status["kokoclone_ja"] = "ready" if is_ready else "unavailable"
            except Exception as e:
                tts_status["kokoclone_ja"] = f"error: {str(e)}"
        else:
            tts_status["kokoclone_ja"] = "not_initialized"

        # Kokoro JP (Japanese secondary)
        if tts_router.kokoro_jp:
            try:
                is_ready = await tts_router.kokoro_jp.health_check()
                tts_status["kokoro_ja"] = "ready" if is_ready else "not_loaded"
            except Exception as e:
                tts_status["kokoro_ja"] = f"error: {str(e)}"
        else:
            tts_status["kokoro_ja"] = "not_initialized"

        # Qwen3 TTS (final fallback)
        if config and not config.qwen3_tts_enabled:
            tts_status["qwen3_tts"] = "disabled"
        elif tts_router and tts_router.qwen3_tts:
            try:
                is_ready = await tts_router.qwen3_tts.health_check()
                tts_status["qwen3_tts"] = "ready" if is_ready else "unavailable"
            except Exception as e:
                tts_status["qwen3_tts"] = f"error: {str(e)}"

        health_status["tts"] = tts_status

    logger.debug("Health check requested")
    return JSONResponse(content=health_status, status_code=200)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    client_id = f"{websocket.client.host}:{websocket.client.port}"
    logger.info(f"WebSocket connection attempt from {client_id}")

    try:
        await websocket.accept()
        logger.info(f"WebSocket connection established: {client_id}")

        from server.pipeline import VoicePipeline
        pipeline = VoicePipeline(
            websocket=websocket,
            config=app_state["config"],
            stt=app_state["stt"],
            llm_chain=app_state["llm_chain"],
            rag=app_state["rag"],
            tts_router=app_state["tts_router"],
        )

        await pipeline.run()

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {client_id}")

    except Exception as e:
        logger.error(f"WebSocket error for {client_id}: {e}", exc_info=True)
        try:
            await websocket.close(code=1011, reason=str(e))
        except Exception:
            pass

    finally:
        logger.info(f"Cleaning up resources for {client_id}")


if __name__ == "__main__":
    import uvicorn

    # Load configuration
    config = Config.from_env()

    # Run server
    logger.info(f"Starting server on {config.host}:{config.port}")
    uvicorn.run(
        "server.main:app",
        host=config.host,
        port=config.port,
        log_level="info",
        access_log=True
    )