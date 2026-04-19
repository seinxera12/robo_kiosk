"""
SearXNG web search client.

Interfaces with self-hosted SearXNG service for web searches.
"""

import httpx
from typing import List, Dict
import logging

logger = logging.getLogger(__name__)


async def searxng_search(
    query: str,
    base_url: str = "http://searxng:8080",
    n_results: int = 3,
    timeout: float = 5.0
) -> List[Dict[str, str]]:
    """
    Search the web using SearXNG.
    
    Args:
        query: Search query string
        base_url: SearXNG service base URL
        n_results: Number of results to return
        timeout: Request timeout in seconds
        
    Returns:
        List of search results with 'title' and 'content' keys
        
    Preconditions:
        - query is non-empty string
        - SearXNG service is running
        
    Postconditions:
        - Returns up to n_results search results
        - Each result has title and content
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{base_url}/search",
                params={
                    "q": query,
                    "format": "json",
                    "language": "auto"
                },
                timeout=timeout
            )
            response.raise_for_status()
            
            data = response.json()
            results = []
            
            for item in data.get("results", [])[:n_results]:
                results.append({
                    "title": item.get("title", ""),
                    "content": item.get("content", ""),
                    "url": item.get("url", "")
                })
            
            logger.info(f"SearXNG search returned {len(results)} results for: {query[:50]}")
            return results
            
    except Exception as e:
        logger.error(f"SearXNG search failed: {e}")
        return []
