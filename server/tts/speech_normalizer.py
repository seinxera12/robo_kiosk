"""
Normalize LLM text for speech synthesis.

The model writes for the *screen*: markdown formatting, cited source URLs, the
occasional code block. Handed to a TTS engine verbatim, that text is read out
literally — "hash hash Opening Hours", and a long URL degrades into spelled-out
characters and symbols.

This module strips the text down to what should actually be *said*.

CONTRACT — read before changing anything here:
    This is for the TTS branch ONLY. The `llm_text_chunk` events streamed to the
    client MUST keep carrying raw, unmodified markdown: the frontend renders it as
    real formatting (headings, bold, code blocks, clickable links). Normalizing on
    the client path would silently break that. Same for conversation_history, which
    should record what the model actually said.

    Speech is a rendering of the text, not a replacement for it.

URLs are DROPPED rather than spoken. The app is a desktop chat window and the
transcript renders links as ordinary clickable links, so the URL is visible and one
click away — reading it aloud carries no information and is pure noise. Speech says
what the source *is*; the screen carries its address.
"""

from __future__ import annotations

import re
from typing import Literal

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

# Bare URLs and bare domains. Deliberately greedy about trailing path/query/fragment
# characters: a half-removed URL is worse than none, because the leftover fragment is
# exactly the unpronounceable garbage this is meant to prevent.
#
# The trailing [^\s]* stops at whitespace, so sentence-final punctuation directly
# attached to a URL ("see https://example.com.") is consumed with it. That is fine —
# the sentence terminator is re-established by the caller's boundary handling, and
# leaving a stray "." behind is harmless.
_BARE_URL = re.compile(
    r"""
    (?:
        (?:https?|ftp)://       # explicit scheme
      | www\.                   # or a www. host with no scheme
    )
    [^\s<>()\[\]{}"']*          # host + path + query + fragment
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Markdown link: [text](url) -> keep the text, drop the address.
_MD_LINK = re.compile(r"\[([^\]\n]*)\]\(\s*<?[^)\s]*>?\s*(?:\"[^\"]*\")?\s*\)")

# Markdown image: ![alt](url) -> drop entirely. An alt-text read aloud mid-sentence
# is confusing, and there is nothing to see in an audio stream anyway.
_MD_IMAGE = re.compile(r"!\[([^\]\n]*)\]\([^)]*\)")

# Bare email-ish / domain-ish tokens that survive the above: "example.com", "foo.co.jp".
# Only matched when the whole token looks like a domain, so ordinary prose and
# abbreviations are untouched.
_BARE_DOMAIN = re.compile(
    r"\b(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+(?:com|org|net|edu|gov|io|jp|co\.jp|ai|dev)\b"
    r"(?:/[^\s]*)?",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Markdown block structure
# ---------------------------------------------------------------------------

# Fenced code block, including an unterminated one (the LLM stream may be cut off
# mid-block, and a half-open fence must not dump raw code into the speech stream).
_CODE_FENCE = re.compile(r"```[^\n]*\n.*?(?:```|\Z)", re.DOTALL)
_CODE_FENCE_INLINE = re.compile(r"```[^\n`]*```")

# Heading: drop the marker, keep the text. A heading is a sentence-ish unit but rarely
# ends in punctuation, so without a terminator it runs straight into the next line and
# the engine reads them as one breathless clause. The caller relies on this producing a
# terminated sentence.
_HEADING = re.compile(r"^[ \t]*#{1,6}[ \t]+(.*?)[ \t]*#*[ \t]*$", re.MULTILINE)

# Horizontal rule: ---, ***, ___ (3+). Must be tested BEFORE list markers and emphasis,
# or "---" is mistaken for a bullet or for italics.
_HR = re.compile(r"^[ \t]*(?:-{3,}|\*{3,}|_{3,})[ \t]*$", re.MULTILINE)

# Blockquote marker at line start.
_BLOCKQUOTE = re.compile(r"^[ \t]*>+[ \t]?", re.MULTILINE)

# Unordered list marker at line start. Requires the trailing space, so a hyphenated
# word or a "*emphasis*" at line start is not eaten.
_UL_MARKER = re.compile(r"^[ \t]*[-*+][ \t]+", re.MULTILINE)

# Ordered list marker at line start: "1. ", "2) ".
_OL_MARKER = re.compile(r"^[ \t]*\d+[.)][ \t]+", re.MULTILINE)

# Table separator row: |---|:---:|
_TABLE_SEP = re.compile(r"^[ \t]*\|?[ \t]*:?-{2,}:?[ \t]*(?:\|[ \t]*:?-{2,}:?[ \t]*)*\|?[ \t]*$", re.MULTILINE)

# Table cell pipes -> comma, so a row is read as a list rather than one run-on phrase.
_TABLE_ROW = re.compile(r"^[ \t]*\|(.+)\|[ \t]*$", re.MULTILINE)

# ---------------------------------------------------------------------------
# Markdown inline emphasis
# ---------------------------------------------------------------------------

_BOLD_ITALIC = re.compile(r"(\*{1,3}|_{1,3})(\S(?:.*?\S)?)\1", re.DOTALL)
_STRIKE = re.compile(r"~~(.*?)~~", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`\n]*)`")

# Leftover markers that survived (unbalanced emphasis from a truncated stream, stray
# pipes, backticks). Swept last: never leave a symbol behind for the engine to voice.
_LEFTOVER_SYMBOLS = re.compile(r"[*_`~|#]+")

# Collapse runs of blank lines / spaces created by all the removals above.
_MULTI_BLANK = re.compile(r"\n{2,}")
_MULTI_SPACE = re.compile(r"[ \t]{2,}")

_SENTENCE_END = ".?!。？！…"


def _strip_urls(text: str) -> str:
    """Remove URLs, keeping markdown link text.

    Order matters: images before links (an image is a link with a leading `!`), and
    markdown links before bare URLs (so `[docs](https://x.com)` keeps "docs" rather
    than having its address ripped out from under it).
    """
    text = _MD_IMAGE.sub("", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _BARE_URL.sub("", text)
    text = _BARE_DOMAIN.sub("", text)
    return text


def _strip_markdown(text: str) -> str:
    """Remove markdown syntax, keeping the words."""
    # Block structure first — an inline rule would otherwise corrupt block markers
    # (e.g. `***` as a horizontal rule read as bold-italic).
    text = _CODE_FENCE.sub(" ", text)
    text = _CODE_FENCE_INLINE.sub(" ", text)
    text = _HR.sub("", text)

    # Headings: terminate them so they don't run into the following line.
    def _heading(m: re.Match) -> str:
        body = m.group(1).strip()
        if not body:
            return ""
        return body if body[-1] in _SENTENCE_END else body + "."

    text = _HEADING.sub(_heading, text)

    text = _TABLE_SEP.sub("", text)
    text = _TABLE_ROW.sub(lambda m: ", ".join(c.strip() for c in m.group(1).split("|") if c.strip()), text)
    text = _BLOCKQUOTE.sub("", text)
    text = _UL_MARKER.sub("", text)
    text = _OL_MARKER.sub("", text)

    # Inline.
    text = _INLINE_CODE.sub(r"\1", text)
    text = _STRIKE.sub(r"\1", text)
    # Twice: nested emphasis like **_both_** needs a second pass to unwrap the inner
    # pair once the outer one is gone.
    text = _BOLD_ITALIC.sub(r"\2", text)
    text = _BOLD_ITALIC.sub(r"\2", text)

    return text


def normalize_for_speech(text: str, lang: Literal["en", "ja"] = "en") -> str:
    """
    Strip markdown and URLs from LLM text so a TTS engine speaks only the words.

    Args:
        text: Raw LLM output (may contain markdown, URLs, code blocks).
        lang: "en" or "ja". Currently only affects nothing structural — the markdown
              syntax an LLM emits is the same in both — but it is threaded through
              because the caller has it and future language-specific rules belong here.

    Returns:
        Speech-ready text. May be an EMPTY STRING if the input was entirely
        non-speech (a lone code block, a bare URL). Callers must check before
        synthesising: handing "" to Kokoro produces a warning and no audio.
    """
    if not text or not text.strip():
        return ""

    text = _strip_urls(text)
    text = _strip_markdown(text)

    # Anything still holding a markdown symbol would be voiced as that symbol.
    text = _LEFTOVER_SYMBOLS.sub("", text)

    text = _MULTI_SPACE.sub(" ", text)
    text = _MULTI_BLANK.sub("\n", text)

    # Tidy the punctuation the removals left stranded: a dropped URL after "see:" can
    # leave " ." or ",," behind, which some engines voice.
    text = re.sub(r"\s+([,.!?;:。、！？])", r"\1", text)
    text = re.sub(r"([,.;:])\1+", r"\1", text)
    text = re.sub(r"\(\s*\)", "", text)

    return text.strip()
