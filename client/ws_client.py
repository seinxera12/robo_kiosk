"""
WebSocket client for server communication.

Handles persistent WebSocket connection with automatic reconnection.
"""

import asyncio
import websockets
import json
from typing import AsyncIterator, Union
import logging

logger = logging.getLogger(__name__)


class WebSocketClient:
    """
    WebSocket client with automatic reconnection.
    
    Manages persistent connection to server with exponential backoff.
    """
    
    def __init__(self, server_url: str):
        """
        Initialize WebSocket client.
        
        Args:
            server_url: WebSocket server URL (ws://server:8765/ws)
        """
        self.server_url = server_url
        self.websocket = None
        self.reconnect_delay = 1.0  # Start with 1 second
        self.max_reconnect_delay = 30.0
        
        logger.info(f"Initialized WebSocket client for {server_url}")
    
    async def connect(self) -> None:
        """
        Establish WebSocket connection.
        
        Raises:
            Exception: If connection fails
        """
        try:
            self.websocket = await websockets.connect(self.server_url)
            self.reconnect_delay = 1.0  # Reset on successful connection
            logger.info("WebSocket connected")
        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            raise
    
    async def reconnect(self) -> None:
        """
        Attempt reconnection with exponential backoff.
        """
        while True:
            try:
                logger.info(f"Attempting reconnection in {self.reconnect_delay}s...")
                await asyncio.sleep(self.reconnect_delay)
                
                await self.connect()
                logger.info("Reconnection successful")
                return
                
            except Exception as e:
                logger.warning(f"Reconnection failed: {e}")
                
                # Exponential backoff
                self.reconnect_delay = min(
                    self.reconnect_delay * 2,
                    self.max_reconnect_delay
                )
    
    async def send_json(self, message: dict) -> None:
        """
        Send JSON message to server.
        
        Args:
            message: Dictionary to send as JSON
        """
        if not self.websocket:
            raise RuntimeError("WebSocket not connected")
        
        try:
            await self.websocket.send(json.dumps(message))
        except Exception as e:
            logger.error(f"Failed to send JSON: {e}")
            await self.reconnect()
    
    async def send_audio(self, audio_bytes: bytes) -> None:
        """
        Send binary audio data to server.
        
        Args:
            audio_bytes: PCM16 audio bytes
        """
        if not self.websocket:
            raise RuntimeError("WebSocket not connected")
        
        try:
            await self.websocket.send(audio_bytes)
        except Exception as e:
            logger.error(f"Failed to send audio: {e}")
            await self.reconnect()
    
    async def receive(self) -> AsyncIterator[Union[dict, bytes]]:
        """
        Receive messages from server.
        
        Yields:
            dict for JSON messages, bytes for binary audio
        """
        while True:
            if not self.websocket:
                await self.reconnect()
            
            try:
                message = await self.websocket.recv()
                
                if isinstance(message, bytes):
                    # Binary audio data
                    yield message
                else:
                    # JSON message
                    yield json.loads(message)
                    
            except websockets.exceptions.ConnectionClosed:
                logger.warning("WebSocket connection closed")
                await self.reconnect()
            except Exception as e:
                logger.error(f"Error receiving message: {e}")
                await self.reconnect()
    
    def is_connected(self) -> bool:
        """
        Check if WebSocket is connected.
        
        Returns:
            True if connected, False otherwise
        """
        return self.websocket is not None and self.websocket.open
    
    async def close(self) -> None:
        """Close WebSocket connection."""
        if self.websocket:
            await self.websocket.close()
            logger.info("WebSocket closed")
