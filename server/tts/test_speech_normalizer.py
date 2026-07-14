"""
Unit tests for speech_normalizer.

The GPU is remote, so the audio itself cannot be heard from here. These tests are the
safety net: they pin the exact text handed to Kokoro.
"""

import pytest

from server.tts.speech_normalizer import normalize_for_speech


class TestMarkdownStripping:
    """Bug #1 — markdown symbols were being spoken aloud."""

    def test_heading_marker_is_not_spoken(self):
        out = normalize_for_speech("## Opening Hours")
        assert "#" not in out
        assert "Opening Hours" in out

    def test_heading_is_terminated_so_it_does_not_run_into_the_next_line(self):
        # Without a terminator the engine reads heading and body as one clause.
        out = normalize_for_speech("## Hours\nWe open at nine.")
        assert "Hours." in out

    def test_heading_already_ending_in_punctuation_is_not_double_terminated(self):
        assert ".." not in normalize_for_speech("## Are we open?")

    def test_bold_and_italic_markers_are_removed(self):
        out = normalize_for_speech("We are **open** and _ready_.")
        assert out == "We are open and ready."

    def test_nested_emphasis(self):
        assert normalize_for_speech("**_both_**") == "both"

    def test_inline_code_backticks_are_removed(self):
        assert normalize_for_speech("Run `npm install` now.") == "Run npm install now."

    def test_fenced_code_block_is_dropped_entirely(self):
        out = normalize_for_speech("Do this:\n```python\nprint('hi')\n```\nThen go.")
        assert "print" not in out
        assert "```" not in out
        assert "Then go." in out

    def test_unterminated_code_fence_is_still_dropped(self):
        # A truncated stream leaves an open fence; raw code must not reach the engine.
        out = normalize_for_speech("Here:\n```python\nprint('hi')")
        assert "print" not in out
        assert "`" not in out

    def test_list_markers_are_removed_but_items_survive(self):
        out = normalize_for_speech("- milk\n- eggs\n1. first\n2) second")
        for token in ("milk", "eggs", "first", "second"):
            assert token in out
        assert "-" not in out

    def test_blockquote_marker_removed(self):
        assert normalize_for_speech("> quoted text") == "quoted text"

    def test_horizontal_rule_removed(self):
        out = normalize_for_speech("Before.\n\n---\n\nAfter.")
        assert "-" not in out
        assert "Before." in out and "After." in out

    def test_table_pipes_are_not_spoken(self):
        out = normalize_for_speech("| Day | Hours |\n| --- | --- |\n| Mon | 9-5 |")
        assert "|" not in out
        assert "Day" in out and "Mon" in out

    def test_strikethrough(self):
        assert normalize_for_speech("~~gone~~ here") == "gone here"

    def test_unbalanced_emphasis_from_a_truncated_stream_leaves_no_symbol(self):
        # Mid-stream the closing ** has not arrived yet.
        assert "*" not in normalize_for_speech("We are **open")


class TestUrls:
    """Bug #3 — long URLs became spelled-out characters and symbols."""

    def test_bare_url_is_dropped(self):
        out = normalize_for_speech("See https://example.com/a/b?c=1#d for details.")
        assert "http" not in out
        assert "example" not in out
        assert "for details." in out

    def test_long_url_with_path_and_query_leaves_no_fragment_behind(self):
        # A half-removed URL is worse than none: the leftover is the garbage.
        out = normalize_for_speech(
            "Source: https://www.city.example.co.jp/docs/2024/opening-hours.html?ref=kiosk"
        )
        for junk in ("http", "www", "://", ".html", "?ref", "/docs"):
            assert junk not in out

    def test_www_url_without_scheme_is_dropped(self):
        assert "www" not in normalize_for_speech("Visit www.example.com today.")

    def test_markdown_link_speaks_the_text_not_the_address(self):
        out = normalize_for_speech("See [the timetable](https://example.com/t) here.")
        assert "the timetable" in out
        assert "example" not in out
        assert "http" not in out

    def test_markdown_image_is_dropped(self):
        out = normalize_for_speech("![a chart](https://example.com/c.png) Done.")
        assert "chart" not in out
        assert "Done." in out

    def test_bare_domain_is_dropped(self):
        assert "example.com" not in normalize_for_speech("Check example.com now.")

    def test_stranded_punctuation_is_tidied_after_a_url_is_removed(self):
        out = normalize_for_speech("Source: https://example.com .")
        assert " ." not in out
        assert ".." not in out


class TestPassthrough:
    """The normalizer must not damage ordinary prose."""

    def test_plain_text_is_unchanged(self):
        text = "The library is open from nine to five on weekdays."
        assert normalize_for_speech(text) == text

    def test_decimals_survive(self):
        # Regression guard: these must not be mangled by URL/domain removal.
        assert "3.5" in normalize_for_speech("It is 3.5 meters wide.")

    def test_abbreviations_survive(self):
        assert "Dr." in normalize_for_speech("Ask Dr. Smith.")

    def test_ordinary_hyphen_is_not_treated_as_a_list_marker(self):
        assert normalize_for_speech("A well-known fact.") == "A well-known fact."

    def test_japanese_prose_is_unchanged(self):
        text = "図書館は九時から五時まで開いています。"
        assert normalize_for_speech(text, "ja") == text

    def test_japanese_markdown_is_stripped(self):
        out = normalize_for_speech("## 開館時間\n**九時**から。", "ja")
        assert "#" not in out and "*" not in out
        assert "開館時間" in out and "九時" in out


class TestEmptyAndDegenerate:
    """Callers must not hand '' to Kokoro — these are the cases that produce it."""

    @pytest.mark.parametrize("text", ["", "   ", "\n\n", None])
    def test_empty_input_returns_empty(self, text):
        assert normalize_for_speech(text or "") == ""

    def test_text_that_is_only_a_url_normalizes_to_empty(self):
        assert normalize_for_speech("https://example.com/a/b") == ""

    def test_text_that_is_only_a_code_block_normalizes_to_empty(self):
        assert normalize_for_speech("```py\nx = 1\n```") == ""

    def test_text_that_is_only_markdown_symbols_normalizes_to_empty(self):
        assert normalize_for_speech("**  **") == ""
