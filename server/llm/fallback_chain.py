"""
LLM fallback chain orchestrator.

Manages automatic failover between vLLM, Ollama, and Grok backends
with health checking and caching of last successful backend.
"""

import asyncio
from typing import AsyncIterator, Optional
import logging

from server.llm.vllm_backend import VLLMBackend
from server.llm.ollama_backend import OllamaBackend
from server.llm.grok_backend import GrokBackend

logger = logging.getLogger(__name__)


class LLMFallbackChain:
    """
    LLM fallback chain with automatic backend failover.
    
    Tries backends in order: vLLM → Ollama → Grok API
    Caches last successful backend for optimization.
    """
    
    def __init__(self, config):
        """
        Initialize fallback chain with all backends.
        
        Args:
            config: Configuration object with backend settings
        """
        self.backends = [
            VLLMBackend(config),
            OllamaBackend(config),
            GrokBackend(config)
        ]
        self._healthy_index = 0  # Cache last successful backend
        logger.info("Initialized LLM fallback chain with 3 backends")
    
    async def health_check(self, backend, timeout: float = 5.0) -> bool:
        """
        Check if backend is healthy and responsive.
        
        Args:
            backend: Backend instance to check
            timeout: Timeout in seconds
            
        Returns:
            True if healthy, False otherwise
        """
        try:
            await asyncio.wait_for(backend.ping(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            logger.warning(f"Backend {backend.__class__.__name__} health check timed out")
            return False
        except Exception as e:
            logger.warning(f"Backend {backend.__class__.__name__} health check failed: {e}")
            return False
    
    async def stream_with_fallback(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None
    ) -> AsyncIterator[str]:
        """
        Stream LLM tokens with automatic backend fallback.
        
        Args:
            messages: List of message dicts
            tools: Optional tool definitions
            
        Yields:
            Text tokens from first successful backend
            
        Raises:
            RuntimeError: If all backends fail
            
        Preconditions:
            - messages is non-empty list
            - Each message has 'role' and 'content'
            
        Postconditions:
            - Yields at least one token if any backend succeeds
            - Updates _healthy_index to last successful backend
        """
        # Try backends starting from last successful
        backends_to_try = (
            self.backends[self._healthy_index:] + 
            self.backends[:self._healthy_index]
        )
        
        for i, backend in enumerate(backends_to_try):
            backend_name = backend.__class__.__name__
            
            # Health check before attempting
            if not await self.health_check(backend):
                logger.info(f"Skipping unhealthy backend: {backend_name}")
                continue
            
            try:
                logger.info(f"Attempting LLM inference with {backend_name}")
                token_count = 0
                
                async for token in backend.stream(messages, tools=tools):
                    token_count += 1
                    yield token
                
                # Success - update cache
                actual_index = self.backends.index(backend)
                self._healthy_index = actual_index
                logger.info(f"Successfully used {backend_name} ({token_count} tokens)")
                return
                
            except Exception as e:
                logger.warning(f"Backend {backend_name} failed: {e}")
                continue
        
        # All backends exhausted
        raise RuntimeError("All LLM backends failed")
