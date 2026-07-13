"""
Search query reformulator module.

Converts raw conversational transcripts into concise English search queries
via a non-streaming LLM call. Handles Japanese-to-English translation
when Japanese characters are detected.

Inference backend: the SAME endpoint the main chat LLM uses (VLLM_BASE_URL —
in the deployed stack, the LiteLLM proxy). It used to call a separate Ollama
service with its own small model, which meant a second model to host, keep warm,
and keep in sync. Routing both through one endpoint removes that.

Two things the old Ollama path did NOT have to deal with, and which are easy to
get wrong here:

  * VLLM_BASE_URL ALREADY INCLUDES the "/v1" suffix (e.g.
    http://litellm:4000/v1). The old code stripped "/v1" and re-appended it;
    doing that here would produce ".../v1/v1/chat/completions".
  * The proxy ENFORCES AUTH. The main backend sends VLLM_API_KEY; a request
    without it is rejected. The old Ollama endpoint needed no key.
"""

import logging

# Logger setup
logger = logging.getLogger(__name__)

# Reformulation is a short, deterministic extraction — not a chat turn.
_MAX_TOKENS = 32
_TEMPERATURE = 0
_TIMEOUT_SECONDS = 10.0


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
    config=None,
) -> str:
    """
    Convert a raw conversational utterance into a concise English search query.

    Makes a synchronous, non-streaming call to the MAIN LLM endpoint (the same
    one the chat backend uses) to reformulate the user's message into a 3-6 word
    English search query. Handles Japanese-to-English translation when Japanese
    characters are detected. Falls back to the original user_message on any
    exception — a failed reformulation degrades search quality, it never breaks
    the turn.

    Args:
        user_message: The verbatim transcript string (transcript.text).
        recent_history: Optional slice of conversation_history. The function
                        internally enforces a hard [-6:] slice regardless of
                        the length supplied by the caller.
        config: Config object supplying VLLM_BASE_URL / VLLM_MODEL_NAME /
                VLLM_API_KEY. The pipeline passes its own Config so the
                reformulator provably hits the same endpoint as the chat LLM.
                Falls back to Config.from_env() when omitted.

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

        # Callers in-process pass the pipeline's Config so we hit exactly the
        # endpoint the chat LLM is using. Standalone callers get the same values
        # from the environment.
        if config is None:
            from server.config import Config

            config = Config.from_env()

        # The main chat LLM's endpoint. VLLM_BASE_URL already ends in /v1 (e.g.
        # http://litellm:4000/v1), so append only the path — never another "/v1".
        base_url = str(config.VLLM_BASE_URL).rstrip("/")
        endpoint = f"{base_url}/chat/completions"
        model = config.VLLM_MODEL_NAME
        # The proxy enforces auth; the main backend always sends this key.
        api_key = getattr(config, "VLLM_API_KEY", None) or "local"

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
            "model": model,
            "messages": messages,
            "stream": False,
            "temperature": _TEMPERATURE,
            "max_tokens": _MAX_TOKENS,
        }

        logger.info(f"🤖 Calling LLM model: {model}")
        logger.info(
            f"⚙️  Model settings: temperature={_TEMPERATURE}, "
            f"max_tokens={_MAX_TOKENS}, stream=False"
        )
        logger.info(f"🌐 LLM endpoint: {endpoint}")

        # Synchronous, non-streaming call against the same OpenAI-compatible
        # endpoint the chat backend uses. The Authorization header is required:
        # the LiteLLM proxy rejects unauthenticated requests.
        call_start = time.time()
        with httpx.Client(timeout=httpx.Timeout(_TIMEOUT_SECONDS)) as client:
            response = client.post(
                endpoint,
                json=request_body,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            response.raise_for_status()

        call_duration = time.time() - call_start
        logger.info(f"⏱️  LLM call completed in {call_duration:.2f}s")
        
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
