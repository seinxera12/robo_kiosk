"""
CosyVoice2 TTS REST API Service.

Provides a simple REST API for English text-to-speech synthesis.
Compatible with the voice kiosk chatbot server.
"""

import asyncio
import io
import logging
from contextlib import asynccontextmanager
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import soundfile as sf
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global model instance and thread pool for blocking inference
cosyvoice_model = None
_executor = ThreadPoolExecutor(max_workers=1)  # single worker — model is not thread-safe


class SynthesisRequest(BaseModel):
    """Request model for TTS synthesis."""
    text: str
    speaker_id: Optional[int] = 0
    speed: Optional[float] = 1.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load CosyVoice2 model on startup."""
    global cosyvoice_model
    
    import os
    import sys
    
    # Add cosyvoice_repo to Python path
    cosyvoice_path = os.path.join(os.path.dirname(__file__), "cosyvoice_repo")
    if cosyvoice_path not in sys.path:
        sys.path.insert(0, cosyvoice_path)
    
    # Add Matcha-TTS to path
    matcha_path = os.path.join(cosyvoice_path, "third_party", "Matcha-TTS")
    if matcha_path not in sys.path:
        sys.path.insert(0, matcha_path)
    
    model_path = os.getenv("COSYVOICE_MODEL_PATH", "iic/CosyVoice2-0.5B")
    
    logger.info(f"Loading CosyVoice2 model: {model_path}")
    
    try:
        from cosyvoice.cli.cosyvoice import AutoModel
        cosyvoice_model = AutoModel(model_dir=model_path)
        logger.info("CosyVoice2 model loaded successfully")
    except Exception as e:
        logger.error(f"Failed to load CosyVoice2 model: {e}", exc_info=True)
        raise
    
    # Resolve cross_lingual prompt wav path
    cross_lingual_wav = os.path.join(cosyvoice_path, "asset", "cross_lingual_prompt.wav")
    if not os.path.exists(cross_lingual_wav):
        logger.error(f"cross_lingual_prompt.wav not found at {cross_lingual_wav}")
    else:
        logger.info(f"Using cross-lingual prompt wav: {cross_lingual_wav}")
    
    app.state.cross_lingual_wav = cross_lingual_wav
    
    yield
    
    cosyvoice_model = None
    _executor.shutdown(wait=False)


app = FastAPI(
    title="CosyVoice2 TTS Service",
    description="REST API for CosyVoice2-0.5B English TTS",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "CosyVoice2 TTS",
        "version": "1.0.0",
        "status": "running" if cosyvoice_model else "model_not_loaded"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    if cosyvoice_model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    return {
        "status": "healthy",
        "model": "CosyVoice2-0.5B",
        "ready": True
    }


@app.get("/speakers")
async def list_speakers():
    """List available speaker IDs."""
    if cosyvoice_model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    try:
        available_speakers = list(cosyvoice_model.frontend.spk2info.keys())
        return {
            "speakers": available_speakers,
            "default": available_speakers[0] if available_speakers else None,
            "count": len(available_speakers)
        }
    except Exception as e:
        logger.error(f"Error listing speakers: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list speakers: {str(e)}")


@app.post("/synthesize")
async def synthesize(request: SynthesisRequest):
    """
    Synthesize speech from text. Streams WAV audio as it is generated.
    
    Uses inference_cross_lingual with <|en|> language tag — forces English
    phoneme generation regardless of the prompt speaker's native language.
    Response is streamed so the client can begin playback before synthesis
    is fully complete.
    """
    if cosyvoice_model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    if not request.text or not request.text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty")
    
    cross_lingual_wav = app.state.cross_lingual_wav
    if not cross_lingual_wav or not __import__('os').path.exists(cross_lingual_wav):
        raise HTTPException(status_code=503, detail="Prompt wav not available")
    
    tagged_text = f"<|en|>{request.text}"
    prompt_wav = cross_lingual_wav
    speed = request.speed

    logger.info(f"Synthesizing: {request.text[:50]}...")

    async def generate():
        """Run synthesis in thread pool and stream WAV chunks as they arrive."""
        loop = asyncio.get_event_loop()
        # Queue for passing audio chunks from the thread to this async generator
        chunk_queue: asyncio.Queue = asyncio.Queue()

        def _run_synthesis():
            """Blocking synthesis — runs in thread executor."""
            try:
                output = cosyvoice_model.inference_cross_lingual(
                    tts_text=tagged_text,
                    prompt_wav=prompt_wav,
                    stream=True,   # generate and yield audio chunks incrementally
                    speed=speed
                )
                for audio_chunk in output:
                    if isinstance(audio_chunk, dict) and 'tts_speech' in audio_chunk:
                        data = audio_chunk['tts_speech']
                        if hasattr(data, 'cpu'):
                            data = data.cpu().numpy()
                        wav_bytes = audio_to_wav(data, sample_rate=24000)
                        # Thread-safe put into asyncio queue
                        loop.call_soon_threadsafe(chunk_queue.put_nowait, wav_bytes)
                    elif isinstance(audio_chunk, np.ndarray):
                        wav_bytes = audio_to_wav(audio_chunk, sample_rate=24000)
                        loop.call_soon_threadsafe(chunk_queue.put_nowait, wav_bytes)
            except Exception as e:
                logger.error(f"Synthesis thread error: {e}", exc_info=True)
            finally:
                # Signal completion
                loop.call_soon_threadsafe(chunk_queue.put_nowait, None)

        # Start synthesis in background thread
        asyncio.get_event_loop().run_in_executor(_executor, _run_synthesis)

        # Yield chunks as they arrive from the synthesis thread
        total_bytes = 0
        while True:
            chunk = await chunk_queue.get()
            if chunk is None:
                break
            total_bytes += len(chunk)
            yield chunk

        logger.info(f"Synthesis complete: {total_bytes} bytes streamed")

    return StreamingResponse(
        generate(),
        media_type="audio/wav",
        headers={"Content-Disposition": "inline; filename=speech.wav"}
    )


def audio_to_wav(audio_data: np.ndarray, sample_rate: int = 22050) -> bytes:
    """
    Convert numpy audio to WAV bytes.
    
    Args:
        audio_data: Audio as numpy array
        sample_rate: Sample rate (CosyVoice2 default is 22050 Hz)
        
    Returns:
        WAV file bytes
    """
    # Ensure audio is 1D
    if audio_data.ndim > 1:
        audio_data = audio_data.squeeze()
    
    # Convert to int16 PCM
    audio_int16 = (audio_data * 32767).astype(np.int16)
    
    # Write to WAV bytes
    wav_buffer = io.BytesIO()
    sf.write(wav_buffer, audio_int16, sample_rate, format='WAV', subtype='PCM_16')
    wav_buffer.seek(0)
    
    return wav_buffer.read()


if __name__ == "__main__":
    import os
    
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5002"))
    
    logger.info(f"Starting CosyVoice2 TTS service on {host}:{port}")
    
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info"
    )
