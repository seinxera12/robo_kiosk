"""
Regression tests for tts_worker: audio ordering, speech normalization, and the
raw-markdown wire contract.

These drive the REAL tts_worker with fakes for the TTS engine and the websocket, so
no GPU and no model load is needed.

The ordering test is the one that matters. The old code did:

    task = asyncio.create_task(_synthesize_and_queue(...))   # fire and forget

so every sentence synthesised concurrently and pushed audio into audio_output
whenever it happened to finish — a short sentence overtook a long one and the reply
was spoken out of order. The fake below reproduces exactly that condition by making
the FIRST sentence the slowest; under the old code its audio arrived last.
"""

import asyncio

import pytest  # noqa: F401

from server.pipeline import VoicePipeline

# Gap between fed tokens. Must be SHORTER than OrderingTTSRouter's synthesis delays so
# that sentences overlap in flight — see the comment on _DELAYS.
_FEED_INTERVAL = 0.02


class FakeConfig:
    use_rag = False
    building_name = "Test Building"
    searxng_url = "http://searxng:8080"
    chromadb_path = "/tmp/chroma"


class FakeWebSocket:
    """Records everything sent, so the client-facing wire format can be asserted."""

    def __init__(self):
        self.json_sent: list[dict] = []
        self.bytes_sent: list[bytes] = []

    async def send_json(self, payload):
        self.json_sent.append(payload)

    async def send_bytes(self, data):
        self.bytes_sent.append(data)

    async def receive(self):
        await asyncio.sleep(3600)  # never


class OrderingTTSRouter:
    """
    Fake TTS router that makes EARLIER sentences SLOWER.

    This is the adversarial case for the old fire-and-forget code: sentence 1 takes
    the longest, so if synthesis is concurrent its audio lands last and the reply is
    spoken out of order. With sequential synthesis the delay cannot reorder anything.
    """

    def __init__(self):
        self.calls: list[str] = []
        self._n = 0

    # Synthesis is deliberately SLOWER than the test's token-feed interval
    # (_FEED_INTERVAL), so sentence N is still synthesising when sentence N+1's
    # boundary is detected. That overlap is the whole point: it is the condition under
    # which the old fire-and-forget code raced. If synthesis finished before the next
    # sentence arrived, concurrent and sequential code would behave identically and the
    # test would pass against the bug — which is exactly what an earlier version of
    # this fake did.
    _DELAYS = (0.30, 0.05, 0.01)  # first sentence slowest -> it lost the race

    async def synthesize_stream(self, text, lang):
        delay = self._DELAYS[min(self._n, len(self._DELAYS) - 1)]
        self._n += 1
        self.calls.append(text)
        # Two chunks per sentence with an await between them — this is what allowed
        # chunks of different sentences to INTERLEAVE under the old code.
        for part in (b"a", b"b"):
            await asyncio.sleep(delay / 2)
            yield text.encode() + part


def _make_pipeline(ws, router):
    return VoicePipeline(
        websocket=ws,
        config=FakeConfig(),
        stt=object(),
        llm_chain=object(),
        rag=None,
        tts_router=router,
    )


async def _drive_tts_worker(pipeline, tokens, timeout=5.0):
    """
    Feed tokens + the end-of-stream sentinel through the real tts_worker.

    Tokens are fed one at a time WITH A YIELD BETWEEN THEM, which is the real streaming
    condition. Dumping them all in at once instead lets tts_worker's non-blocking drain
    (a deliberate anti-backlog feature) scoop every sentence into a single buffer and
    synthesise them as one call — which would vacuously "pass" an ordering test by never
    producing more than one sentence to order.
    """
    worker = asyncio.create_task(pipeline.tts_worker())
    await asyncio.sleep(0)  # let the worker reach its first await
    for tok in tokens:
        await pipeline.state.token.put(tok)
        # Long enough for the worker to see the boundary and START synthesising, but
        # SHORTER than synthesis takes — so sentence N is still in flight when N+1
        # arrives. That overlap is what the old concurrent code got wrong.
        await asyncio.sleep(_FEED_INTERVAL)
    await pipeline.state.token.put(None)  # LLM stream finished

    # Wait until synthesis has drained, then stop the worker.
    async def _settled():
        while True:
            await asyncio.sleep(0.02)
            if pipeline.state.token.empty() and not pipeline._synthesis_tasks:
                await asyncio.sleep(0.05)
                if not pipeline._synthesis_tasks:
                    return

    try:
        await asyncio.wait_for(_settled(), timeout=timeout)
    finally:
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass


def _drain(queue):
    out = []
    while not queue.empty():
        out.append(queue.get_nowait())
    return out


def _run(tokens):
    """
    Drive the real tts_worker over `tokens` and return (router, pipeline).

    Sync wrapper around asyncio.run: the project does not depend on pytest-asyncio,
    and a TTS fix is not a reason to add a test dependency to a deployed server.
    """
    ws = FakeWebSocket()
    router = OrderingTTSRouter()
    pipeline = _make_pipeline(ws, router)
    pipeline.state.current_turn = {"lang": "en"}
    asyncio.run(_drive_tts_worker(pipeline, tokens))
    return router, pipeline


class TestAudioOrdering:
    """Bug #2 — sentences were spoken out of order / interleaved."""

    # Tokens end ON the terminator, as a real LLM streams them ("here", "."), so the
    # buffer momentarily ends in "." and the boundary fires. A token ending in a
    # trailing SPACE would (correctly) not close the sentence, and all three would
    # accumulate into one buffer — vacuously passing by never producing an order.
    SENTENCES = ["Alpha one here.", "Beta two here.", "Gamma three here."]

    def test_audio_reaches_the_output_queue_in_sentence_order(self):
        """
        THE regression test for bug #2.

        Asserts on audio_output — the queue whose order is what the user actually
        HEARS — not on the order synthesis was *started* in, which was already correct
        even when broken. The fake makes the first sentence by far the slowest, so
        under fire-and-forget its audio landed last and the reply was spoken backwards.
        """
        _, pipeline = _run(self.SENTENCES)
        chunks = [c.decode() for c in _drain(pipeline.state.audio_output)]
        assert len(chunks) >= 4, f"expected several chunks to order, got {chunks}"

        # First letter identifies the sentence: Alpha, Beta, Gamma.
        order = [c[0] for c in chunks]
        assert order == sorted(order, key="ABG".index), (
            f"audio left the pipeline out of order (or interleaved): {chunks}"
        )

    def test_every_sentence_is_synthesised_exactly_once(self):
        router, _ = _run(self.SENTENCES)
        assert router.calls == self.SENTENCES


class TestSpeechNormalizationIsApplied:
    """Bugs #1 and #3 — as seen by the worker, end to end."""

    def test_markdown_symbols_never_reach_the_tts_engine(self):
        router, _ = _run(["## Opening Hours\n", "We are **open** now. "])
        spoken = " ".join(router.calls)
        assert "#" not in spoken
        assert "*" not in spoken
        assert "open" in spoken

    def test_url_is_not_split_and_not_spoken(self):
        # The dots in this URL used to cut it into unpronounceable fragments.
        router, _ = _run(["See https://www.example.com/a/b.html for details. "])
        spoken = " ".join(router.calls)
        assert "http" not in spoken
        assert "example" not in spoken
        assert "for details" in spoken

    def test_a_chunk_that_is_only_a_url_is_not_synthesised_as_empty(self):
        router, _ = _run(["https://example.com/only "])
        # Normalisation empties it; Kokoro must never be handed "".
        assert all(c.strip() for c in router.calls)


class TestWireFormatContract:
    """
    The frontend renders the assistant's markdown (headings, bold, clickable links).
    It can only do that if the server keeps sending RAW markdown to the client.

    Normalisation is a TTS-side rendering. If someone ever "fixes" the markdown bug by
    stripping it in llm_worker instead, the display silently loses all formatting —
    this test is what stops that.
    """

    def test_normalizer_is_not_applied_to_the_client_path(self):
        import inspect

        from server import pipeline as pipeline_module

        src = inspect.getsource(pipeline_module.VoicePipeline.llm_worker)
        assert "normalize_for_speech" not in src, (
            "llm_worker must NOT normalise: llm_text_chunk carries raw markdown to the "
            "frontend, which renders it as formatting."
        )

    def test_tts_worker_is_the_only_caller(self):
        import inspect

        from server import pipeline as pipeline_module

        src = inspect.getsource(pipeline_module.VoicePipeline.tts_worker)
        assert "normalize_for_speech" in src
