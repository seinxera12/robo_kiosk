"""
vLLM backend with OpenAI-compatible API.

Primary LLM backend using vLLM for fast local inference.
"""

from openai import AsyncOpenAI
from typing import AsyncIterator, Optional
import logging

logger = logging.getLogger(__name__)


class VLLMBackend:
    """
    vLLM backend with OpenAI-compatible API.
    
    Provides fast local LLM inference with streaming support.
    """
    
    def __init__(self, config):
        """
        Initialize vLLM client.
        
        Args:
            config: Configuration object with VLLM_BASE_URL and VLLM_MODEL_NAME
        """
        self.client = AsyncOpenAI(
            base_url=config.VLLM_BASE_URL,
            api_key="local"  # vLLM doesn't require real API key
        )
        self.model = config.VLLM_MODEL_NAME
        logger.info(f"Initialized vLLM backend: {self.model} at {config.VLLM_BASE_URL}")
    
    async def ping(self) -> None:
        """
        Health check via models list endpoint.
        
        Raises:
            Exception: If vLLM is unreachable or unhealthy
        """
        await self.client.models.list()
    
    async def stream(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None
    ) -> AsyncIterator[str]:
        """
        Stream completion tokens from vLLM.
        
        Args:
            messages: List of message dicts
            tools: Optional tool definitions
            
        Yields:
            Text tokens as generated
        """
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            stream=True,
            max_tokens=512,
            temperature=0.7
        )
        
        async for chunk in response:
            delta = chunk.choices[0].delta
            
            if delta.content:
                yield delta.content
            
            # TODO: Handle tool calls if needed
            elif delta.tool_calls:
                logger.debug(f"Tool call received: {delta.tool_calls}")
