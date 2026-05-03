"""
Server configuration management.

Loads all service configuration from environment variables.
"""

import os
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv

# Load .env.local first (local overrides), then .env as fallback.
# override=False means already-set shell vars take highest priority.
load_dotenv(".env.local", override=False)
load_dotenv(".env", override=False)


@dataclass
class Config:
    """Server configuration loaded from environment variables."""
    
    # LLM Backend Configuration
    vllm_base_url: str
    vllm_model_name: str
    ollama_base_url: str
    ollama_model_name: str
    grok_api_key: Optional[str]
    
    # STT Configuration
    stt_model: str
    stt_compute_type: str
    
    # TTS Configuration
    tts_en_engine: str
    tts_jp_url: str
    
    
    
    # RAG Configuration
    chromadb_path: str
    building_name: str
    
    # Web Search Configuration
    searxng_url: str
    
    # Server Configuration
    host: str
    port: int
    
    # Feature toggles
    use_rag: bool = True  # Set to False to skip RAG retrieval entirely

    # Kiosk metadata (set per connection)
    kiosk_metadata: dict = None

    stt_device: str = "cuda"
    cosyvoice_model_path: str = "iic/CosyVoice2-0.5B"
    cosyvoice_url: str = "http://localhost:5002"
    cosyvoice_device: str = "cuda"

    # Kokoro-82M TTS (English primary engine)
    kokoro_voice: str = "af_heart"   # American female — best general-purpose voice
    kokoro_speed: float = 1.0        # Speech rate multiplier
    kokoro_device: str = "cpu"       # "cpu" or "cuda" — Kokoro runs fine on CPU
    kokoro_lang: str = "a"           # "a" = American English, "b" = British English

    # Kokoro-82M Japanese TTS (Japanese primary engine)
    kokoro_jp_voice: str = "jf_alpha"  # Best overall Japanese female voice
    kokoro_jp_enabled: bool = True     # Set False to skip Kokoro JP and use VOICEVOX directly

    # KokoClone zero-shot voice cloning TTS (Japanese primary engine when configured)
    kokoclone_ref_audio: Optional[str] = None   # Path to reference WAV file (3–10 s); None = disabled
    kokoclone_enabled: bool = True              # Set False to skip KokoClone and use KokoroJP instead
    kokoclone_url: str = "http://localhost:5003" # KokoClone microservice URL
    
    def __post_init__(self):
        """Initialize mutable defaults."""
        if self.kiosk_metadata is None:
            self.kiosk_metadata = {"location": "Unknown", "id": "unknown"}
    
    # Compatibility properties for backend classes
    @property
    def VLLM_BASE_URL(self):
        return self.vllm_base_url
    
    @property
    def VLLM_MODEL_NAME(self):
        return self.vllm_model_name
    
    @property
    def OLLAMA_BASE_URL(self):
        return self.ollama_base_url
    
    @property
    def OLLAMA_MODEL_NAME(self):
        return self.ollama_model_name
    
    @property
    def GROK_API_KEY(self):
        return self.grok_api_key
    
    @property
    def CHROMADB_PATH(self):
        return self.chromadb_path
    
    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables."""
        return cls(
            # LLM Backend Configuration
            vllm_base_url=os.getenv("VLLM_BASE_URL", "http://localhost:8000"),
            vllm_model_name=os.getenv("VLLM_MODEL_NAME", "Qwen/Qwen2.5-7B-Instruct-AWQ"),
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            ollama_model_name=os.getenv("OLLAMA_MODEL_NAME", "qwen2.5:7b-instruct"),
            grok_api_key=os.getenv("GROK_API_KEY"),
            
            # STT Configuration
            stt_model=os.getenv("STT_MODEL", "large-v3"),
            stt_compute_type=os.getenv("STT_COMPUTE_TYPE", "float16"),
            stt_device=os.getenv("STT_DEVICE", "cuda"),
            
            # TTS Configuration
            tts_en_engine=os.getenv("TTS_EN_ENGINE", "cosyvoice2"),
            tts_jp_url=os.getenv("TTS_JP_URL", "http://localhost:50021"),
            cosyvoice_url=os.getenv("COSYVOICE_URL", "http://localhost:5002"),
            
            # RAG Configuration
            chromadb_path=os.getenv("CHROMADB_PATH", "/chroma"),
            building_name=os.getenv("BUILDING_NAME", "Office Building"),
            
            # Web Search Configuration
            searxng_url=os.getenv("SEARXNG_URL", "http://searxng:8080"),
            
            # Server Configuration
            host=os.getenv("SERVER_HOST", "0.0.0.0"),
            port=int(os.getenv("SERVER_PORT", "8765")),
            
            # Feature toggles
            use_rag=os.getenv("USE_RAG", "true").lower() not in ("false", "0", "no"),

            # Kokoro TTS
            kokoro_voice=os.getenv("KOKORO_VOICE", "af_heart"),
            kokoro_speed=float(os.getenv("KOKORO_SPEED", "1.0")),
            kokoro_device=os.getenv("KOKORO_DEVICE", "cpu"),
            kokoro_lang=os.getenv("KOKORO_LANG", "a"),
            kokoro_jp_voice=os.getenv("KOKORO_JP_VOICE", "jf_alpha"),
            kokoro_jp_enabled=os.getenv("KOKORO_JP_ENABLED", "true").lower() not in ("false", "0", "no"),

            # KokoClone zero-shot voice cloning TTS
            kokoclone_ref_audio=os.getenv("KOKOCLONE_REF_AUDIO"),
            kokoclone_enabled=os.getenv("KOKOCLONE_ENABLED", "true").lower() not in ("false", "0", "no"),
            kokoclone_url=os.getenv("KOKOCLONE_URL", "http://localhost:5003"),
        )
