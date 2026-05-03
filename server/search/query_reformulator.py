"""
Search query reformulator module.

Converts raw conversational transcripts into concise English search queries
via a non-streaming Ollama call. Handles Japanese-to-English translation
when Japanese characters are detected.
"""

import logging

# Module-level constants
OLLAMA_BASE_URL: str = "http://localhost:11434"
REFORMULATOR_MODEL: str = "qwen2.5:3b-instruct"

# Logger setup
logger = logging.getLogger(__name__)


def _is_japanese(text: str) -> bool:
    """
    Detect if text contains Japanese characters.
    
    Returns True if any character falls in Unicode ranges:
    - U+3040–U+30FF (hiragana and katakana)
    - U+4E00–U+9FAF (CJK unified ideographs)
    
    Args:
        text: The input string to check.
        
    Returns:
        True if Japanese characters are detected, False otherwise.
    """
    return any(
        ('\u3040' <= c <= '\u30ff') or ('\u4e00' <= c <= '\u9faf')
        for c in text
    )


def _build_system_prompt(is_japanese: bool) -> str:
    """
    Build the system prompt for the query reformulation LLM call.
    
    The system prompt instructs the model to extract a concise 3-6 word
    English search query. For Japanese input, it explicitly instructs
    translation to English.
    
    Args:
        is_japanese: Whether Japanese characters were detected in the input.
        
    Returns:
        The system prompt string.
    """
    if is_japanese:
        return (
            "You are a search query extractor. Your only job is to translate the user's "
            "Japanese message into a concise English web search query of 3 to 6 words. "
            "Output only the English search query. No explanation. No punctuation at the end. "
            "No quotes. One line only."
        )
    else:
        return (
            "You are a search query extractor. Your only job is to convert the user's "
            "conversational message into a concise English web search query of 3 to 6 words. "
            "Output only the search query. No explanation. No punctuation at the end. No quotes. "
            "One line only."
        )


def extract_search_query(
    user_message: str,
    recent_history: list[dict] | None = None,
) -> str:
    """
    Convert a raw conversational utterance into a concise English search query.
    
    Makes a synchronous, non-streaming call to Ollama to reformulate the user's
    message into a 3-6 word English search query. Handles Japanese-to-English
    translation when Japanese characters are detected. Falls back to the original
    user_message on any exception.
    
    Args:
        user_message: The verbatim transcript string (transcript.text).
        recent_history: Optional slice of conversation_history. The function
                        internally enforces a hard [-6:] slice regardless of
                        the length supplied by the caller.
    
    Returns:
        A concise English search query string (stripped of whitespace).
        Falls back to user_message on any exception.
    """
    logger.info("=" * 80)
    logger.info("🔍 QUERY REFORMULATION START")
    logger.info("=" * 80)
    
    try:
        import httpx
        import time
        
        start_time = time.time()
        
        # Log input
        logger.info(f"📝 Original user message: '{user_message}'")
        logger.info(f"📊 Message length: {len(user_message)} characters")
        
        # Enforce hard history slice: at most 6 messages
        history_slice = (recent_history or [])[-6:]
        history_count = len(history_slice)
        logger.info(f"📚 Conversation history: {history_count} messages (max 6)")
        
        if history_count > 0:
            logger.info("   Recent context:")
            for i, entry in enumerate(history_slice[-3:], 1):  # Show last 3 for brevity
                role_icon = "👤" if entry["role"] == "user" else "🤖"
                content_preview = entry["content"][:60] + "..." if len(entry["content"]) > 60 else entry["content"]
                logger.info(f"   {role_icon} {entry['role']}: {content_preview}")
        
        # Detect Japanese and build system prompt
        is_japanese = _is_japanese(user_message)
        lang_detected = "Japanese (日本語)" if is_japanese else "English"
        logger.info(f"🌐 Language detected: {lang_detected}")
        
        system_prompt = _build_system_prompt(is_japanese)
        prompt_type = "Translation + Extraction" if is_japanese else "Extraction"
        logger.info(f"📋 Prompt type: {prompt_type}")
        
        # Build messages array: [system] + [history...] + [current_user]
        messages = [{"role": "system", "content": system_prompt}]
        
        # Add history slice (pass through as-is, preserving role/content)
        for entry in history_slice:
            # Pass through role and content; ignore 'lang' field but don't strip it
            messages.append({
                "role": entry["role"],
                "content": entry["content"]
            })
        
        # Add current user message as the last element
        messages.append({"role": "user", "content": user_message})
        
        total_messages = len(messages)
        logger.info(f"💬 Total messages in context: {total_messages} (1 system + {history_count} history + 1 current)")
        
        # Build request body for OpenAI-compatible API
        request_body = {
            "model": REFORMULATOR_MODEL,
            "messages": messages,
            "stream": False,
            "temperature": 0,
            "max_tokens": 32,
        }
        
        logger.info(f"🤖 Calling Ollama model: {REFORMULATOR_MODEL}")
        logger.info(f"⚙️  Model settings: temperature=0, max_tokens=32, stream=False")
        logger.info(f"🌐 Ollama endpoint: {OLLAMA_BASE_URL}/v1/chat/completions")
        
        # Make synchronous HTTP call with 10-second timeout
        # Use OpenAI-compatible endpoint (/v1/chat/completions) instead of native Ollama API
        call_start = time.time()
        with httpx.Client(timeout=httpx.Timeout(10.0)) as client:
            response = client.post(
                f"{OLLAMA_BASE_URL}/v1/chat/completions",
                json=request_body,
            )
            response.raise_for_status()
        
        call_duration = time.time() - call_start
        logger.info(f"⏱️  Ollama call completed in {call_duration:.2f}s")
        
        # Parse OpenAI-compatible response format
        response_data = response.json()
        reformulated_query = response_data["choices"][0]["message"]["content"].strip()
        
        total_duration = time.time() - start_time
        
        # Log results
        logger.info("─" * 80)
        logger.info("✅ REFORMULATION SUCCESS")
        logger.info(f"📤 Reformulated query: '{reformulated_query}'")
        logger.info(f"📏 Query length: {len(reformulated_query)} characters")
        logger.info(f"⏱️  Total duration: {total_duration:.2f}s")
        
        # Show transformation
        if user_message != reformulated_query:
            logger.info("🔄 Transformation applied:")
            logger.info(f"   Before: '{user_message[:80]}'")
            logger.info(f"   After:  '{reformulated_query}'")
        else:
            logger.info("ℹ️  No transformation (query unchanged)")
        
        logger.info("=" * 80)
        
        return reformulated_query
    
    except Exception as e:
        logger.warning("─" * 80)
        logger.warning(f"⚠️  REFORMULATION FAILED: {type(e).__name__}: {e}")
        logger.warning(f"🔄 Falling back to original input: '{user_message}'")
        logger.warning("=" * 80)
        return user_message
