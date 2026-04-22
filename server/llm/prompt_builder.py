"""
LLM prompt builder — intent-aware, multi-source context augmentation.

Three system prompt modes:
  BUILDING  — navigation assistant + RAG building knowledge
  SEARCH    — research assistant + web search snippets
  GENERAL   — general-purpose assistant, no external context

Context budget (Qwen 3B, 4096 token window):
  System prompt:      ~250 tokens  (fixed)
  Augmented context:  ~600 tokens  (RAG or search results)
  History:           ~1500 tokens  (trimmed from oldest if over budget)
  Current query:       ~50 tokens
  Response headroom: ~1696 tokens
  Safety trim threshold: 3000 input tokens → trim history
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from server.llm.intent_classifier import Intent

# ---------------------------------------------------------------------------
# System prompt templates
# ---------------------------------------------------------------------------

_BUILDING_SYSTEM = """\
You are a helpful, friendly building assistant for {building_name}.
You help visitors navigate the building, find rooms and facilities, and answer questions about the building.

Current Information:
- Date/Time: {datetime}
- Kiosk Location: {kiosk_location}

Building Knowledge:
{rag_context}

CRITICAL LANGUAGE RULE - STRICTLY ENFORCE:
- ALWAYS respond in the SAME LANGUAGE as the user's question
- User language detected as: {user_language}
- If user_language is "en": Respond ONLY in English, no Japanese characters AT ALL
- If user_language is "ja": Respond ONLY in Japanese using polite form (です・ます体), no English words AT ALL
- NEVER mix languages or switch languages based on content
- IGNORE any language cues in the question content - only follow the detected user_language

RESPONSE FORMAT REQUIREMENT:
- For English (user_language="en"): Use only English alphabet, numbers, and punctuation
- For Japanese (user_language="ja"): Use only Japanese characters (hiragana, katakana, kanji) and Japanese punctuation
- VIOLATION OF LANGUAGE RULE IS STRICTLY FORBIDDEN

Guidelines:
- Give clear, concise directions using landmarks (e.g. "near the north elevator")
- If the building knowledge above doesn't cover the question, say so honestly
- Keep responses brief and conversational
"""

_SEARCH_SYSTEM = """\
You are a helpful, knowledgeable assistant for {building_name}.
You have access to recent web search results to answer questions about current events, weather, news, and real-time information.

Current Information:
- Date/Time: {datetime}
- Kiosk Location: {kiosk_location}

Web Search Results:
{search_context}

CRITICAL LANGUAGE RULE - STRICTLY ENFORCE:
- ALWAYS respond in the SAME LANGUAGE as the user's question
- User language detected as: {user_language}
- If user_language is "en": Respond ONLY in English, no Japanese characters
- If user_language is "ja": Respond ONLY in Japanese using polite form (です・ます体), no English words
- NEVER mix languages or switch languages based on content
- IGNORE any language cues in the question content - only follow the detected user_language

SEARCH RESPONSE RULES - MANDATORY:
- FIRST: Check if the web search results above contain relevant information for the user's question
- If search results contain relevant information: MUST use them to provide a comprehensive answer
- Extract specific facts, numbers, dates, and details from the search results
- Synthesize information from multiple search results when available
- If search results are empty or completely irrelevant: Say "I couldn't find current information about that"
- NEVER ignore relevant search results - they contain the most current information available
- ALWAYS prioritize search result information over general knowledge for current events/data

Guidelines:
- Base your answer primarily on the search results above when they are relevant
- Include specific details from the search results (prices, dates, numbers, etc.)
- Keep responses informative and factual
- Mention sources when providing specific data or claims
- If search results are partial, provide what information is available and suggest where to find more
"""

_GENERAL_SYSTEM = """\
You are a helpful, friendly assistant at {building_name}.
You can answer general questions, have conversations, help with calculations, explain concepts, and assist with a wide range of topics.

Current Information:
- Date/Time: {datetime}
- Kiosk Location: {kiosk_location}

CRITICAL LANGUAGE RULE - STRICTLY ENFORCE:
- ALWAYS respond in the SAME LANGUAGE as the user's question
- User language detected as: {user_language}
- If user_language is "en": Respond ONLY in English, no Japanese characters AT ALL
- If user_language is "ja": Respond ONLY in Japanese using polite form (です・ます体), no English words AT ALL
- NEVER mix languages or switch languages based on content
- IGNORE any language cues in the question content - only follow the detected user_language

RESPONSE FORMAT REQUIREMENT:
- For English (user_language="en"): Use only English alphabet, numbers, and punctuation
- For Japanese (user_language="ja"): Use only Japanese characters (hiragana, katakana, kanji) and Japanese punctuation
- VIOLATION OF LANGUAGE RULE IS STRICTLY FORBIDDEN

Guidelines:
- Be concise, warm, and helpful
- If you don't know something, say so honestly
"""

_SYSTEM_TEMPLATES = {
    Intent.BUILDING: _BUILDING_SYSTEM,
    Intent.SEARCH:   _SEARCH_SYSTEM,
    Intent.GENERAL:  _GENERAL_SYSTEM,
}

# ---------------------------------------------------------------------------
# Context budget
# ---------------------------------------------------------------------------

# Rough token estimate: 1 token ≈ 4 characters (conservative for mixed lang)
_CHARS_PER_TOKEN = 4
_MAX_INPUT_TOKENS = 3000   # leave ~1000 for response within 4096 window
_MAX_INPUT_CHARS  = _MAX_INPUT_TOKENS * _CHARS_PER_TOKEN


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _trim_history(history: list[dict], budget_chars: int) -> list[dict]:
    """
    Trim oldest history turns until total chars fit within budget.
    Always keeps at least the last 2 messages (1 turn) for coherence.
    """
    if not history:
        return history

    total = sum(len(t.get("content", "")) for t in history)
    trimmed = list(history)

    while total > budget_chars and len(trimmed) > 2:
        removed = trimmed.pop(0)
        total -= len(removed.get("content", ""))

    return trimmed


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_messages(
    user_text: str,
    lang: Literal["en", "ja"],
    context: str,
    history: list[dict],
    kiosk_meta: dict,
    building_name: str = "Building",
    intent: Intent = Intent.BUILDING,
) -> list[dict]:
    """
    Build the LLM message list for a given intent.

    Args:
        user_text:     Current user query
        lang:          Detected language
        context:       Augmented context string (RAG chunks or search snippets)
        history:       Prior conversation turns [{role, content}, ...]
        kiosk_meta:    {"location": ..., "building_name": ...}
        building_name: Building name
        intent:        Classified intent (BUILDING | SEARCH | GENERAL)

    Returns:
        List of message dicts ready for any OpenAI-compatible backend.
    """
    template = _SYSTEM_TEMPLATES[intent]

    # Fill template placeholders — unused ones get a safe default
    system_content = template.format(
        building_name=building_name,
        datetime=datetime.now().strftime("%Y-%m-%d %H:%M"),
        kiosk_location=kiosk_meta.get("location", "Unknown"),
        rag_context=context    if context else "(No relevant building information found)",
        search_context=context if context else "(No search results available)",
        user_language=lang,  # Add explicit language parameter
    )

    # Budget: system + user query are fixed; trim history to fit
    fixed_chars = len(system_content) + len(user_text)
    history_budget = _MAX_INPUT_CHARS - fixed_chars
    trimmed_history = _trim_history(list(history), history_budget)

    # Append language enforcement directly to the system message so it is
    # never ignored.  A second "system" role message is silently dropped by
    # most OpenAI-compatible backends (vLLM, Ollama), which is why the
    # language instruction was being lost.
    if lang == "ja":
        lang_reminder = (
            "\n\n---\n"
            "【絶対ルール】必ず日本語のみで回答してください。英語は一切使用禁止です。\n"
            "回答は日本語（ひらがな・カタカナ・漢字）のみで書いてください。"
        )
    else:
        lang_reminder = (
            "\n\n---\n"
            "ABSOLUTE RULE: Respond in English only. "
            "Do not use any Japanese characters whatsoever."
        )

    messages: list[dict] = [{"role": "system", "content": system_content + lang_reminder}]

    for turn in trimmed_history:
        role    = turn.get("role")
        content = turn.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": user_text})

    # Log budget usage
    total_chars = sum(len(m["content"]) for m in messages)
    estimated_tokens = _estimate_tokens(str(messages))
    history_turns = len(trimmed_history) // 2
    original_turns = len(history) // 2
    if history_turns < original_turns:
        import logging
        logging.getLogger(__name__).info(
            f"History trimmed: {original_turns} → {history_turns} turns "
            f"(budget {_MAX_INPUT_TOKENS} tokens)"
        )

    import logging
    logging.getLogger(__name__).debug(
        f"Prompt built | intent={intent.value} | "
        f"~{estimated_tokens} tokens | history={history_turns} turns"
    )

    return messages


def format_rag_context(chunks: str) -> str:
    """Pass-through — RAG already returns concatenated text."""
    return chunks


def format_search_context(results: list[dict]) -> str:
    """
    Format SearXNG results into a compact context block.

    Args:
        results: List of {"title": ..., "content": ..., "url": ...}

    Returns:
        Formatted string for injection into the search system prompt.
    """
    if not results:
        return ""

    lines = []
    for i, r in enumerate(results, 1):
        title   = r.get("title", "").strip()
        content = r.get("content", "").strip()
        url     = r.get("url", "").strip()
        if title or content:
            lines.append(f"[{i}] {title}")
            if content:
                lines.append(f"    {content[:300]}")   # cap per-result length
            if url:
                lines.append(f"    Source: {url}")
            lines.append("")

    return "\n".join(lines).strip()
