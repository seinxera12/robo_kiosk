"""
Client main entry point.

Initializes and runs the kiosk client application.
"""

import asyncio
import sys
import signal
import logging
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


class KioskClient:
    """
    Main kiosk client application.
    
    Coordinates all client components.
    """
    
    def __init__(self, config):
        """
        Initialize kiosk client.
        
        Args:
            config: Configuration object
        """
        self.config = config
        
        # Import components
        from client.audio_capture import AudioCapture
        from client.vad import SileroVAD
        from client.ws_client import WebSocketClient
        from client.audio_playback import AudioPlayback
        from client.ui.app import KioskMainWindow
        
        # Initialize components
        self.audio_capture = AudioCapture()
        self.vad = SileroVAD()
        self.ws_client = WebSocketClient(config.server_ws_url)
        self.playback = AudioPlayback()
        self.ui = KioskMainWindow()
        
        logger.info("Initialized kiosk client")
    
    async def run(self) -> None:
        """
        Main client loop.
        
        Runs until shutdown signal received.
        """
        try:
            # Connect to server
            await self.ws_client.connect()
            
            # Send session_start message
            await self.ws_client.send_json({
                "type": "session_start",
                "kiosk_id": self.config.kiosk_id,
                "kiosk_location": self.config.kiosk_location
            })
            
            # Start audio capture and processing
            await self._process_audio()
            
            logger.info("Client running")
            
            # Keep running
            while True:
                await asyncio.sleep(1)
                
        except Exception as e:
            logger.error(f"Client error: {e}")
            raise
    
    async def _process_audio(self):
        """Process audio capture and VAD."""
        async for audio_frame in self.audio_capture.stream():
            vad_event = self.vad.process_frame(audio_frame)
            
            if vad_event.event_type == "speech_end":
                # Send audio to server
                await self.ws_client.send_audio(vad_event.audio_buffer)
    
    async def shutdown(self) -> None:
        """Graceful shutdown."""
        logger.info("Shutting down client...")
        
        # Close connections and cleanup
        await self.ws_client.close()
        
        logger.info("Client shutdown complete")


def main():
    """Main entry point."""
    # Load configuration
    from client.config import ClientConfig
    config = ClientConfig.from_env()
    
    # Create Qt application
    app = QApplication(sys.argv)
    
    # Create client
    client = KioskClient(config)
    
    # Setup signal handlers
    def signal_handler(sig, frame):
        logger.info("Received shutdown signal")
        asyncio.create_task(client.shutdown())
        app.quit()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Run event loop with Qt integration
    try:
        logger.info("Starting kiosk client application")
        
        # Create asyncio event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Start client in background
        loop.create_task(client.run())
        
        # Use QTimer to process asyncio events
        timer = QTimer()
        timer.timeout.connect(lambda: loop.run_until_complete(asyncio.sleep(0)))
        timer.start(10)  # Process every 10ms
        
        # Run Qt event loop
        sys.exit(app.exec())
        
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
        asyncio.run(client.shutdown())


if __name__ == "__main__":
    main()
