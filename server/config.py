"""
Server configuration management.

Loads all service configuration from environment variables.
"""

import os
from dataclasses import dataclass
from typing import Optional


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
    tts_cosyvoice_model: str = "iic/CosyVoice2-0.5B"
    tts_cosyvoice_device: str = "cuda"
    
    # RAG Configuration
    chromadb_path: str
    building_name: str
    
    # Web Search Configuration
    searxng_url: str
    
    # Server Configuration
    host: str
    port: int
    
    # Kiosk metadata (set per connection)
    kiosk_metadata: dict = None
    
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
            stt_model=os.getenv("STT_MODEL", "large-v3-turbo"),
            stt_compute_type=os.getenv("STT_COMPUTE_TYPE", "float16"),
            
            # TTS Configuration
            tts_en_engine=os.getenv("TTS_EN_ENGINE", "cosyvoice2"),
            tts_jp_url=os.getenv("TTS_JP_URL", "http://localhost:50021"),
            tts_cosyvoice_model=os.getenv("COSYVOICE_MODEL_PATH", "iic/CosyVoice2-0.5B"),
            tts_cosyvoice_device=os.getenv("COSYVOICE_DEVICE", "cuda"),
            
            # RAG Configuration
            chromadb_path=os.getenv("CHROMADB_PATH", "/chroma"),
            building_name=os.getenv("BUILDING_NAME", "Office Building"),
            
            # Web Search Configuration
            searxng_url=os.getenv("SEARXNG_URL", "http://searxng:8080"),
            
            # Server Configuration
            host=os.getenv("SERVER_HOST", "0.0.0.0"),
            port=int(os.getenv("SERVER_PORT", "8765")),
        )
