"""
Client main entry point.

Supports two modes:
  - Full UI mode (default): PyQt6 kiosk window
  - Headless mode (--no-ui): terminal-based, no display required
"""

import asyncio
import sys
import signal
import logging
import argparse

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Headless mode
# ---------------------------------------------------------------------------

async def run_headless(config) -> None:
    """
    Headless client: microphone → VAD → WebSocket → print LLM text.

    No PyQt6, no display required. Useful for WSL2 without WSLg.
    Press Ctrl+C to quit.
    """
    from client.ws_client import WebSocketClient
    from client.audio_capture import AudioCapture
    from client.vad import SileroVAD

    ws = WebSocketClient(config.server_ws_url)
    audio_capture = AudioCapture()
    vad = SileroVAD()

    logger.info("Connecting to server...")
    await ws.connect()

    await ws.send_json({
        "type": "session_start",
        "kiosk_id": config.kiosk_id,
        "kiosk_location": config.kiosk_location,
    })
    logger.info(f"Session started — kiosk_id={config.kiosk_id}")
    print("\n[Headless mode] Speak into your microphone. Press Ctrl+C to quit.\n")

    async def receive_loop():
        """Print server responses to terminal."""
        response_buffer = ""
        async for msg in ws.receive():
            if isinstance(msg, dict):
                msg_type = msg.get("type")
                if msg_type == "llm_text_chunk":
                    text = msg.get("text", "")
                    final = msg.get("final", False)
                    if text:
                        print(text, end="", flush=True)
                        response_buffer += text
                    if final:
                        print()  # newline after full response
                        response_buffer = ""
                elif msg_type == "session_ack":
                    logger.info("Server ready")
                elif msg_type == "status":
                    logger.info(f"Server status: {msg.get('state')}")
                # binary audio chunks are ignored in headless mode (no playback)

    async def capture_loop():
        """Capture mic → VAD → send speech to server."""
        async for frame in audio_capture.stream():
            event = vad.process_frame(frame)
            if event and event.event_type == "speech_end" and event.audio_buffer:
                logger.info(f"Speech detected ({len(event.audio_buffer)} bytes) — sending to server")
                await ws.send_audio(event.audio_buffer)

    # Run both loops concurrently; either finishing stops both
    try:
        await asyncio.gather(receive_loop(), capture_loop())
    except asyncio.CancelledError:
        pass
    finally:
        await ws.close()
        logger.info("Headless client stopped")


# ---------------------------------------------------------------------------
# Text-only headless mode (no microphone — type queries in terminal)
# ---------------------------------------------------------------------------

async def run_headless_text(config) -> None:
    """
    Text-only headless client: type queries, see LLM responses.

    No microphone, no display. Good for quick pipeline testing.
    Type a message and press Enter. Type 'quit' to exit.
    """
    from client.ws_client import WebSocketClient

    ws = WebSocketClient(config.server_ws_url)

    logger.info("Connecting to server...")
    await ws.connect()

    await ws.send_json({
        "type": "session_start",
        "kiosk_id": config.kiosk_id,
        "kiosk_location": config.kiosk_location,
    })
    print("\n[Text mode] Type a message and press Enter. Type 'quit' to exit.\n")

    async def receive_loop():
        async for msg in ws.receive():
            if isinstance(msg, dict):
                msg_type = msg.get("type")
                if msg_type == "llm_text_chunk":
                    text = msg.get("text", "")
                    final = msg.get("final", False)
                    if text:
                        print(text, end="", flush=True)
                    if final:
                        print()
                        print("\nYou: ", end="", flush=True)

    async def input_loop():
        loop = asyncio.get_event_loop()
        print("You: ", end="", flush=True)
        while True:
            # Read input without blocking the event loop
            text = await loop.run_in_executor(None, sys.stdin.readline)
            text = text.strip()
            if not text:
                continue
            if text.lower() in ("quit", "exit", "q"):
                break
            await ws.send_json({
                "type": "text_input",
                "text": text,
                "lang": "en",
            })

    try:
        await asyncio.gather(receive_loop(), input_loop())
    except asyncio.CancelledError:
        pass
    finally:
        await ws.close()
        logger.info("Text client stopped")


# ---------------------------------------------------------------------------
# Full UI mode
# ---------------------------------------------------------------------------

def run_qt(config) -> None:
    """Launch the full PyQt6 kiosk UI."""
    from PyQt6.QtWidgets import QApplication
    from client.ui.app import KioskMainWindow

    app = QApplication(sys.argv)

    window = KioskMainWindow(config=config)
    window.show()

    sys.exit(app.exec())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Voice Kiosk Client")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--no-ui",
        action="store_true",
        help="Headless mode: microphone + VAD, no display required",
    )
    mode.add_argument(
        "--text",
        action="store_true",
        help="Text mode: type queries in terminal, no microphone or display needed",
    )
    args = parser.parse_args()

    from client.config import ClientConfig
    config = ClientConfig.from_env()

    if args.text:
        asyncio.run(run_headless_text(config))
    elif args.no_ui:
        asyncio.run(run_headless(config))
    else:
        run_qt(config)


if __name__ == "__main__":
    main()
