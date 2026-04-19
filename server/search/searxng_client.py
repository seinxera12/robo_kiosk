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
    timeout: float = 8.0
) -> List[Dict[str, str]]:
    """
    Search the web using SearXNG (async, non-blocking).

    Args:
        query:     Search query string
        base_url:  SearXNG service base URL
        n_results: Number of results to return
        timeout:   Total request timeout in seconds (default 8s)

    Returns:
        List of search results with 'title', 'content', 'url' keys.
        Returns empty list on any failure — caller handles fallback.
    """
    try:
        # Separate connect vs read timeouts to avoid blocking on slow DNS
        limits  = httpx.Limits(max_connections=5, max_keepalive_connections=2)
        timeout_cfg = httpx.Timeout(connect=3.0, read=timeout, write=3.0, pool=3.0)

        async with httpx.AsyncClient(limits=limits, timeout=timeout_cfg) as client:
            response = await client.get(
                f"{base_url}/search",
                params={
                    "q": query,
                    "format": "json",
                    "language": "auto",
                },
            )
            response.raise_for_status()

            data = response.json()
            results = []

            for item in data.get("results", [])[:n_results]:
                results.append({
                    "title":   item.get("title", ""),
                    "content": item.get("content", ""),
                    "url":     item.get("url", ""),
                })

            logger.info(f"SearXNG: {len(results)} results for '{query[:50]}'")
            return results

    except httpx.ConnectError:
        logger.warning("SearXNG unreachable — is the container running?")
        return []
    except httpx.TimeoutException:
        logger.warning(f"SearXNG timed out after {timeout}s")
        return []
    except Exception as e:
        logger.error(f"SearXNG search failed: {e}")
        return []
