"""
Unit tests for the Kokoro sentence splitters.

Pure functions — no model load, no GPU. These pin the two bugs the splitter had:
  * short fragments were silently DROPPED, so short replies were never spoken
  * "." split decimals and abbreviations into unpronounceable fragments
"""

from server.tts.kokoro_tts import _split_sentences, _split_sentences_ja


class TestNothingIsDropped:
    """Bug #4 — the old splitter discarded fragments < 3 chars."""

    def test_short_reply_is_still_spoken(self):
        # "OK." was being thrown away entirely: the model wrote it, so it must be said.
        assert _split_sentences("OK.") == ["OK."]

    def test_every_sentence_survives(self):
        out = _split_sentences("The library is open. It closes at five.")
        assert out == ["The library is open.", "It closes at five."]

    def test_no_visible_text_is_lost(self):
        text = "Yes. The east wing is closed today. Sorry."
        joined = " ".join(_split_sentences(text))
        for word in ("Yes", "east wing", "closed", "Sorry"):
            assert word in joined

    def test_tiny_fragment_is_merged_not_discarded(self):
        out = _split_sentences("Go north. A. Then left.")
        assert "A." in " ".join(out)


class TestDotIsNotAlwaysASentenceEnd:
    """Bug #4b — splitting on a bare '.' produced fragments the engine spelled out."""

    def test_decimal_does_not_split(self):
        assert _split_sentences("It is 3.5 meters wide.") == ["It is 3.5 meters wide."]

    def test_version_number_does_not_split(self):
        assert len(_split_sentences("Install v1.2.3 now.")) == 1

    def test_abbreviation_does_not_split(self):
        out = _split_sentences("Ask Dr. Smith about it.")
        assert out == ["Ask Dr. Smith about it."]

    def test_filename_does_not_split(self):
        # No whitespace after the dot, so it was never a boundary.
        assert len(_split_sentences("Open index.html first.")) == 1

    def test_real_boundaries_still_split(self):
        assert len(_split_sentences("One. Two. Three.")) == 3

    def test_question_and_exclamation_split(self):
        assert len(_split_sentences("Are we open? Yes! Come in.")) == 3


class TestJapaneseSplitter:
    """The JA splitter already merged rather than dropped — guard that it stays so."""

    def test_splits_on_japanese_terminator(self):
        assert _split_sentences_ja("開いています。閉まります。") == [
            "開いています。",
            "閉まります。",
        ]

    def test_nothing_is_dropped(self):
        joined = "".join(_split_sentences_ja("はい。図書館は九時からです。"))
        assert "はい" in joined and "九時" in joined


class TestDegenerate:
    def test_empty(self):
        assert _split_sentences("") == []
        assert _split_sentences("   ") == []

    def test_text_with_no_terminator_is_still_returned(self):
        # A flushed tail with no punctuation must still be spoken, not swallowed.
        assert _split_sentences("no terminator here") == ["no terminator here"]
