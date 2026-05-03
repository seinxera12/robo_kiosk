"""
Ollama backend with OpenAI-compatible API.

Secondary LLM backend using Ollama for local inference fallback.
"""

from openai import AsyncOpenAI
from typing import AsyncIterator, Optional
import logging

logger = logging.getLogger(__name__)


class OllamaBackend:
    """
    Ollama backend with OpenAI-compatible API.
    
    Provides local LLM inference as fallback when vLLM is unavailable.
    """
    
    def __init__(self, config):
        """
        Initialize Ollama client.
        
        Args:
            config: Configuration object with OLLAMA_BASE_URL and OLLAMA_MODEL_NAME
        """
        self.client = AsyncOpenAI(
            base_url=config.OLLAMA_BASE_URL,
            api_key="ollama"  # Ollama doesn't require real API key
        )
        self.model = config.OLLAMA_MODEL_NAME
        logger.info(f"Initialized Ollama backend: {self.model} at {config.OLLAMA_BASE_URL}")
    
    async def ping(self) -> None:
        """
        Health check via models list endpoint.
        
        Raises:
            Exception: If Ollama is unreachable or unhealthy
        """
        await self.client.models.list()
    
    async def stream(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None
    ) -> AsyncIterator[str]:
        """
        Stream completion tokens from Ollama.
        
        Args:
            messages: List of message dicts
            tools: Optional tool definitions (may not be supported)
            
        Yields:
            Text tokens as generated
            
        Raises:
            RuntimeError: If Ollama returns no tokens (model not found or empty response)
        """
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=True,
            max_tokens=512,
            temperature=0.3
        )
        
        token_count = 0
        async for chunk in response:
            delta = chunk.choices[0].delta
            if delta.content:
                token_count += 1
                yield delta.content

        if token_count == 0:
            raise RuntimeError(
                f"Ollama returned 0 tokens for model '{self.model}'. "
                f"Check the model is pulled: `ollama pull {self.model}`"
            )
