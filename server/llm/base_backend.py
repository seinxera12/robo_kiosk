"""
Base interface for LLM backends.

Defines the protocol that all LLM backends must implement
for compatibility with the fallback chain.
"""

from typing import Protocol, AsyncIterator, Optional


class BaseLLMBackend(Protocol):
    """
    Interface contract for all LLM backends.
    
    All backend implementations must provide ping() for health checks
    and stream() for token streaming.
    """
    
    async def ping(self) -> None:
        """
        Health check for backend availability.
        
        Raises:
            Exception: If backend is unavailable or unhealthy
        """
        ...
    
    async def stream(
        self, 
        messages: list[dict], 
        tools: Optional[list[dict]] = None
    ) -> AsyncIterator[str]:
        """
        Stream text tokens from LLM.
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            tools: Optional list of tool definitions for function calling
            
        Yields:
            Text tokens as they are generated
            
        Raises:
            Exception: On fatal error during streaming
        """
        ...
