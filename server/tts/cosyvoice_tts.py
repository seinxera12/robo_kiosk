"""
CosyVoice2 English TTS engine via REST API.

Connects to CosyVoice service running on separate server/container.
"""

from typing import AsyncIterator
import logging
import struct
import httpx

logger = logging.getLogger(__name__)


class CosyVoiceTTS:
    """
    CosyVoice2 English TTS engine via REST API.
    
    Connects to CosyVoice service for synthesis.
    """
    
    def __init__(self, config):
        """
        Initialize CosyVoice2 TTS client.

        Args:
            config: Server config object
        """
        self.base_url = getattr(config, "cosyvoice_url", "http://localhost:5002")
        # Use explicit per-phase timeouts.
        # connect: service is local, 5s is generous.
        # read:    CosyVoice synthesis can take 10-30s for long sentences
        #          (RTF ~1.0 means 24s audio takes ~24s to generate).
        #          120s covers even very long sentences with margin.
        # write/pool: short, requests are small JSON payloads.
        self.timeout = httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0)

        logger.info(f"Initialized CosyVoice2 TTS client at {self.base_url}")
    
    async def health_check(self) -> bool:
        """
        Check if CosyVoice service is healthy.
        
        Returns:
            True if service is ready
        """
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{self.base_url}/health", timeout=5.0)
                if resp.status_code == 200:
                    logger.debug("CosyVoice service health check passed")
                    return True
                else:
                    logger.warning(f"CosyVoice service health check failed: HTTP {resp.status_code}")
                    return False
        except httpx.TimeoutException:
            logger.warning("CosyVoice health check timed out")
            return False
        except Exception as e:
            logger.warning(f"CosyVoice health check failed: {e}")
            return False
    
    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        """
        Synthesize English text to audio via REST API using HTTP streaming.

        The CosyVoice service yields multiple complete WAV files in a single
        HTTP response (one per synthesis chunk).  HTTP chunked transfer does
        NOT align to WAV boundaries, so we reassemble complete WAV files from
        the raw byte stream before yielding each one.  This lets the pipeline
        start playing the first sentence of audio while the model is still
        generating the rest.

        Args:
            text: English text to synthesize

        Yields:
            Complete WAV audio bytes, one per synthesis chunk
        """
        if not text or not text.strip():
            logger.warning("Empty text provided for synthesis")
            return

        try:
            logger.debug(f"Synthesizing with CosyVoice service: {text[:50]}...")

            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/synthesize",
                    json={"text": text},
                    timeout=self.timeout,
                ) as resp:
                    resp.raise_for_status()

                    # Reassemble complete WAV files from the raw byte stream.
                    # WAV format: bytes 0-3 = "RIFF", bytes 4-7 = uint32 LE
                    # (file_size - 8), so total file size = value + 8.
                    buf = bytearray()
                    total_yielded = 0

                    async for raw in resp.aiter_bytes(chunk_size=8192):
                        if not raw:
                            continue
                        buf.extend(raw)

                        # Consume as many complete WAV files as are in buf
                        while True:
                            # Need at least 8 bytes for RIFF header
                            if len(buf) < 8:
                                break

                            # Validate RIFF magic
                            if buf[:4] != b"RIFF":
                                # Corrupted stream — discard up to next RIFF
                                next_riff = buf.find(b"RIFF", 1)
                                if next_riff == -1:
                                    logger.warning(
                                        f"No RIFF header in {len(buf)} bytes, discarding"
                                    )
                                    buf.clear()
                                else:
                                    logger.warning(
                                        f"Skipping {next_riff} non-RIFF bytes"
                                    )
                                    del buf[:next_riff]
                                break

                            # Read declared WAV size
                            chunk_data_size = struct.unpack_from("<I", buf, 4)[0]
                            wav_total = chunk_data_size + 8  # RIFF header is 8 bytes

                            if len(buf) < wav_total:
                                # Haven't received the full WAV yet — wait for more
                                break

                            # Extract exactly one complete WAV and yield it
                            wav_bytes = bytes(buf[:wav_total])
                            del buf[:wav_total]
                            total_yielded += len(wav_bytes)
                            logger.debug(
                                f"Yielding WAV chunk: {len(wav_bytes)} bytes"
                            )
                            yield wav_bytes

                    # Flush any remaining complete WAV in the buffer
                    if len(buf) >= 8 and buf[:4] == b"RIFF":
                        chunk_data_size = struct.unpack_from("<I", buf, 4)[0]
                        wav_total = chunk_data_size + 8
                        if len(buf) >= wav_total:
                            wav_bytes = bytes(buf[:wav_total])
                            total_yielded += len(wav_bytes)
                            yield wav_bytes
                        else:
                            logger.warning(
                                f"Incomplete trailing WAV ({len(buf)}/{wav_total} bytes), discarding"
                            )

                    if total_yielded == 0:
                        logger.warning("CosyVoice service returned empty audio")
                    else:
                        logger.debug(
                            f"CosyVoice synthesis complete: {total_yielded} bytes total"
                        )

        except httpx.TimeoutException:
            logger.error(f"CosyVoice synthesis timeout after {self.timeout}s")
        except httpx.HTTPStatusError as e:
            logger.error(
                f"CosyVoice synthesis HTTP error: {e.response.status_code} - {e.response.text}"
            )
        except Exception as e:
            logger.error(f"CosyVoice synthesis error: {e}", exc_info=True)
