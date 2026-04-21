"""
CosyVoice2 TTS REST API Service.

Provides a simple REST API for English text-to-speech synthesis.
Compatible with the voice kiosk chatbot server.
"""

import io
import logging
from contextlib import asynccontextmanager
from typing import Optional

import numpy as np
import soundfile as sf
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global model instance
cosyvoice_model = None


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
    device = os.getenv("COSYVOICE_DEVICE", "cuda")
    
    logger.info(f"Loading CosyVoice2 model: {model_path} on {device}")
    
    try:
        from cosyvoice.cli.cosyvoice import AutoModel
        cosyvoice_model = AutoModel(model_dir=model_path)
        logger.info("CosyVoice2 model loaded successfully")
    except Exception as e:
        logger.error(f"Failed to load CosyVoice2 model: {e}", exc_info=True)
        raise
    
    yield
    
    # Cleanup (if needed)
    cosyvoice_model = None


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
    Synthesize speech from text.
    
    Returns WAV audio bytes.
    """
    if cosyvoice_model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    if not request.text or not request.text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty")
    
    try:
        logger.info(f"Synthesizing: {request.text[:50]}...")
        
        # Use zero-shot inference with a simple English prompt
        prompt_text = "Hello, this is a natural English voice."
        
        # Use the official zero-shot prompt from CosyVoice assets
        # CosyVoice inference_zero_shot expects file path, not numpy array
        import os
        cosyvoice_path = os.path.join(os.path.dirname(__file__), "cosyvoice_repo")
        prompt_wav_path = os.path.join(cosyvoice_path, "asset", "zero_shot_prompt.wav")
        
        logger.debug("Starting zero-shot inference")
        output = cosyvoice_model.inference_zero_shot(
            request.text, 
            prompt_text, 
            prompt_wav_path, 
            stream=False
        )
        
        # Extract audio from generator
        audio_data = None
        for audio_chunk in output:
            if isinstance(audio_chunk, dict) and 'tts_speech' in audio_chunk:
                audio_data = audio_chunk['tts_speech']
                # Convert to numpy if tensor
                if hasattr(audio_data, 'cpu'):
                    audio_data = audio_data.cpu().numpy()
                break
            elif isinstance(audio_chunk, np.ndarray):
                audio_data = audio_chunk
                break
        
        if audio_data is None:
            raise HTTPException(status_code=500, detail="Synthesis failed: no audio generated")
        
        # Convert to WAV bytes
        wav_bytes = audio_to_wav(audio_data, sample_rate=22050)
        
        logger.info(f"Synthesis complete: {len(wav_bytes)} bytes")
        
        # Return WAV audio
        return Response(
            content=wav_bytes,
            media_type="audio/wav",
            headers={
                "Content-Disposition": "inline; filename=speech.wav"
            }
        )
        
    except Exception as e:
        logger.error(f"Synthesis error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Synthesis failed: {str(e)}")


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
