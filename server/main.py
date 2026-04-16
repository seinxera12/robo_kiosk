"""
FastAPI server for real-time streaming voice chatbot.

Provides WebSocket endpoint for bidirectional audio/text communication
and HTTP health check endpoint.

Requirements: 3.1, 3.7, 23.1, 23.4, 23.5
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from server.config import Config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# Application state
app_state = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    
    Initializes configuration and resources on startup,
    cleans up on shutdown.
    """
    # Startup: Load configuration
    logger.info("Starting voice chatbot server...")
    config = Config.from_env()
    app_state["config"] = config
    logger.info(f"Server configured: host={config.host}, port={config.port}")
    
    yield
    
    # Shutdown: Cleanup resources
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
    
    health_status = {
        "status": "healthy",
        "service": "voice-kiosk-chatbot",
        "version": "1.0.0",
    }
    
    if config:
        health_status["config"] = {
            "building_name": config.building_name,
            "stt_model": config.stt_model,
            "tts_en_engine": config.tts_en_engine,
        }
    
    logger.debug("Health check requested")
    return JSONResponse(content=health_status, status_code=200)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time voice interaction (Requirements 3.1, 3.7).
    
    Handles bidirectional communication:
    - Upstream: Binary PCM16 audio frames, JSON control messages
    - Downstream: Binary Opus audio frames, JSON event messages
    
    Connection lifecycle:
    1. Accept connection
    2. Wait for session_start message
    3. Process audio/text inputs
    4. Stream responses
    5. Handle disconnection gracefully
    
    Args:
        websocket: WebSocket connection instance
    """
    client_id = f"{websocket.client.host}:{websocket.client.port}"
    logger.info(f"WebSocket connection attempt from {client_id}")
    
    try:
        # Accept WebSocket connection (Requirement 3.1)
        await websocket.accept()
        logger.info(f"WebSocket connection established: {client_id}")
        
        # Initialize pipeline for this connection
        from server.pipeline import VoicePipeline
        config = app_state.get("config")
        
        pipeline = VoicePipeline(websocket, config)
        
        # Run pipeline until disconnect
        await pipeline.run()
    
    except WebSocketDisconnect:
        logger.info(f"WebSocket connection closed during handshake: {client_id}")
    
    except Exception as e:
        logger.error(f"WebSocket error for {client_id}: {e}", exc_info=True)
        try:
            await websocket.close(code=1011, reason=f"Server error: {str(e)}")
        except Exception:
            pass  # Connection already closed
    
    finally:
        # Cleanup: Clear conversation history and resources (Requirement 3.7)
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
