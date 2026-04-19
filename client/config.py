"""
Client configuration management.

Loads WebSocket URL and kiosk metadata from environment variables.
"""

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv(".env.local", override=False)
load_dotenv(".env", override=False)


@dataclass
class ClientConfig:
    """Client configuration loaded from environment variables."""
    
    # WebSocket Configuration
    server_ws_url: str
    
    # Kiosk Metadata
    kiosk_id: str
    kiosk_location: str
    
    @classmethod
    def from_env(cls) -> "ClientConfig":
        """Load configuration from environment variables."""
        return cls(
            server_ws_url=os.getenv("SERVER_WS_URL", "ws://localhost:8765/ws"),
            kiosk_id=os.getenv("KIOSK_ID", "kiosk-01"),
            kiosk_location=os.getenv("KIOSK_LOCATION", "Floor 1 Lobby"),
        )


# Alias for convenience
Config = ClientConfig
