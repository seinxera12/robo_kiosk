"""
Grok API backend (cloud fallback).

Tertiary LLM backend using xAI's Grok API as last resort fallback.
Logs privacy warnings when used as data leaves local network.
"""

from openai import AsyncOpenAI
from typing import AsyncIterator, Optional
import logging

logger = logging.getLogger(__name__)


class GrokBackend:
    """
    Grok API backend (cloud fallback).
    
    Provides cloud-based LLM inference when all local backends fail.
    PRIVACY WARNING: Data leaves local network when this backend is used.
    """
    
    def __init__(self, config):
        """
        Initialize Grok API client.
        
        Args:
            config: Configuration object with GROK_API_KEY
            
        Raises:
            ValueError: If GROK_API_KEY is not set
        """
        if not config.GROK_API_KEY:
            raise ValueError("GROK_API_KEY required for Grok backend")
        
        self.client = AsyncOpenAI(
            base_url="https://api.x.ai/v1",
            api_key=config.GROK_API_KEY
        )
        self.model = "llama-3.3-70b-versatile"
        logger.info("Initialized Grok API backend (cloud fallback)")
    
    async def ping(self) -> None:
        """
        Health check via models list endpoint.
        
        Raises:
            Exception: If Grok API is unreachable or unhealthy
        """
        await self.client.models.list()
    
    async def stream(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None
    ) -> AsyncIterator[str]:
        """
        Stream completion tokens from Grok API.
        
        PRIVACY WARNING: This sends data to external cloud service.
        
        Args:
            messages: List of message dicts
            tools: Optional tool definitions
            
        Yields:
            Text tokens as generated
        """
        logger.warning("⚠️  Using Grok API fallback - data leaves local network")
        
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=True,
            max_tokens=512,
            temperature=0.7
        )
        
        async for chunk in response:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content
