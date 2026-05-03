"""
Property-based tests for query_reformulator module.

Uses Hypothesis to verify correctness properties across a wide range of inputs.
Each property test runs a minimum of 100 iterations.
"""

import copy
from contextlib import contextmanager
from unittest.mock import Mock, patch

import httpx
import pytest
from hypothesis import given, settings, strategies as st

from server.search.query_reformulator import extract_search_query


# ============================================================================
# Helper Functions
# ============================================================================

@contextmanager
def capture_ollama_request(user_message, recent_history=None):
    """
    Context manager that captures the JSON body sent to Ollama.
    
    Patches httpx.Client.post to intercept the request and return a valid
    response, then yields the captured request body for assertion.
    
    Args:
        user_message: The user message to pass to extract_search_query.
        recent_history: Optional history to pass to extract_search_query.
    
    Yields:
        dict: The JSON request body sent to Ollama.
    """
    captured_request = {}
    
    mock_response = Mock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "captured query"}}]
    }
    mock_response.raise_for_status = Mock()
    
    with patch("httpx.Client") as mock_client:
        mock_post = mock_client.return_value.__enter__.return_value.post
        mock_post.return_value = mock_response
        
        # Call the function
        extract_search_query(user_message, recent_history=recent_history)
        
        # Capture the request body
        if mock_post.called:
            captured_request.update(mock_post.call_args[1]["json"])
    
    yield captured_request


@contextmanager
def mock_ollama_success(response_text):
    """
    Context manager that mocks a successful Ollama response.
    
    Args:
        response_text: The content string to return in the response.
    
    Yields:
        None
    """
    mock_response = Mock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": response_text}}]
    }
    mock_response.raise_for_status = Mock()
    
    with patch("httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.post.return_value = mock_response
        yield


@contextmanager
def mock_ollama_raises(exc):
    """
    Context manager that mocks Ollama to raise an exception.
    
    Args:
        exc: The exception instance or class to raise.
    
    Yields:
        None
    """
    with patch("httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.post.side_effect = exc
        yield


# ============================================================================
# Property Tests
# ============================================================================

class TestProperty1NonEmptyOutput:
    """
    Property 1: Non-empty output invariant
    
    **Validates: Requirements 6.2, 3.1**
    
    For any non-empty user_message string, extract_search_query SHALL return
    a non-empty string — whether the Ollama call succeeds or fails.
    """
    
    @given(st.text(min_size=1))
    @settings(max_examples=100)
    def test_non_empty_output_on_success(self, user_message):
        """Test that successful Ollama call returns non-empty output."""
        with mock_ollama_success("some query"):
            result = extract_search_query(user_message)
        
        # Result should be non-empty (len > 0)
        assert len(result) > 0
    
    @given(st.text(min_size=1))
    @settings(max_examples=100)
    def test_non_empty_output_on_failure(self, user_message):
        """Test that failed Ollama call returns non-empty output (fallback)."""
        with mock_ollama_raises(httpx.ConnectError("Connection failed")):
            result = extract_search_query(user_message)
        
        # Result should be non-empty (len > 0) - fallback returns original input
        assert len(result) > 0


class TestProperty2FallbackPreservesInput:
    """
    Property 2: Fallback preserves original input
    
    **Validates: Requirements 3.1, 3.2**
    
    For any user_message string and any exception raised by the httpx client,
    extract_search_query SHALL return exactly user_message (unmodified).
    """
    
    @given(
        st.text(min_size=1),
        st.sampled_from([
            httpx.ConnectError("Connection failed"),
            httpx.TimeoutException("Timeout"),
            KeyError("missing key"),
            ValueError("invalid value"),
            Exception("generic error"),
        ])
    )
    @settings(max_examples=100)
    def test_fallback_returns_original(self, user_message, exc):
        """Test that any exception triggers fallback to original input."""
        with mock_ollama_raises(exc):
            result = extract_search_query(user_message)
        
        assert result == user_message


class TestProperty3WhitespaceStripped:
    """
    Property 3: Whitespace is always stripped
    
    **Validates: Requirements 1.5**
    
    For any string returned by the mocked Ollama endpoint (including strings
    with arbitrary leading and trailing whitespace), the value returned by
    extract_search_query SHALL equal ollama_response.strip().
    """
    
    @given(
        st.text(min_size=0, max_size=50),
        st.text(alphabet=" \t\n\r", min_size=0, max_size=10)
    )
    @settings(max_examples=100)
    def test_whitespace_stripped(self, core_content, padding):
        """Test that whitespace is stripped from Ollama response."""
        raw_response = padding + core_content + padding
        
        with mock_ollama_success(raw_response):
            result = extract_search_query("any query")
        
        assert result == raw_response.strip()


class TestProperty4JapaneseDetectionDrivesPrompt:
    """
    Property 4: Japanese detection drives system prompt selection
    
    **Validates: Requirements 2.1, 2.3**
    
    For any user_message containing Japanese characters (U+3040–U+30FF or
    U+4E00–U+9FAF), the system prompt SHALL contain a translation instruction.
    For any user_message without Japanese characters, the system prompt SHALL
    NOT contain that translation instruction.
    """
    
    @given(
        st.text(
            alphabet=st.characters(min_codepoint=0x3040, max_codepoint=0x30FF),
            min_size=1,
            max_size=50
        )
    )
    @settings(max_examples=100)
    def test_japanese_input_uses_translation_prompt(self, japanese_text):
        """Test that Japanese input triggers translation system prompt."""
        with capture_ollama_request(japanese_text) as captured:
            system_msg = captured["messages"][0]["content"]
            assert "translate" in system_msg.lower()
    
    @given(
        st.text(
            alphabet=st.characters(max_codepoint=0x302F),
            min_size=1,
            max_size=50
        )
    )
    @settings(max_examples=100)
    def test_non_japanese_input_no_translation_prompt(self, ascii_text):
        """Test that non-Japanese input does not trigger translation prompt."""
        with capture_ollama_request(ascii_text) as captured:
            system_msg = captured["messages"][0]["content"]
            assert "translate" not in system_msg.lower()


class TestProperty5HistorySliceLimit:
    """
    Property 5: History slice hard limit
    
    **Validates: Requirements 7.2**
    
    For any recent_history list of arbitrary length ≥ 0, the number of history
    messages prepended in the Ollama request messages array SHALL be at most 6,
    regardless of the length of the list supplied by the caller.
    """
    
    @given(
        st.lists(
            st.fixed_dictionaries({
                "role": st.sampled_from(["user", "assistant"]),
                "content": st.text(min_size=1, max_size=50)
            }),
            min_size=7,
            max_size=50
        )
    )
    @settings(max_examples=100)
    def test_history_slice_limit(self, long_history):
        """Test that history is sliced to at most 6 messages."""
        with capture_ollama_request("query", recent_history=long_history) as captured:
            messages = captured["messages"]
            # messages = [system] + [history...] + [current_user]
            history_messages = messages[1:-1]
            assert len(history_messages) <= 6


class TestProperty6CurrentMessageLast:
    """
    Property 6: Current message is always last
    
    **Validates: Requirements 7.3**
    
    For any non-empty recent_history, the final element of the messages array
    in the Ollama request SHALL be {"role": "user", "content": user_message}
    (the current user message), and all history entries SHALL appear before it.
    """
    
    @given(
        st.text(min_size=1, max_size=50),
        st.lists(
            st.fixed_dictionaries({
                "role": st.sampled_from(["user", "assistant"]),
                "content": st.text(min_size=1, max_size=50)
            }),
            min_size=1,
            max_size=10
        )
    )
    @settings(max_examples=100)
    def test_current_message_is_last(self, user_message, history):
        """Test that current user message is always the last element."""
        with capture_ollama_request(user_message, recent_history=history) as captured:
            messages = captured["messages"]
            last_msg = messages[-1]
            
            assert last_msg["role"] == "user"
            assert last_msg["content"] == user_message


class TestProperty7HistoryNotMutated:
    """
    Property 7: recent_history is not mutated
    
    **Validates: Requirements 7.4**
    
    For any recent_history list passed to extract_search_query, the list SHALL
    have the same length and identical contents after the function returns as
    it did before the call.
    """
    
    @given(
        st.lists(
            st.fixed_dictionaries({
                "role": st.sampled_from(["user", "assistant"]),
                "content": st.text(min_size=1, max_size=50)
            }),
            min_size=0,
            max_size=10
        )
    )
    @settings(max_examples=100)
    def test_history_not_mutated(self, history):
        """Test that recent_history is not mutated by the function."""
        original = copy.deepcopy(history)
        
        with mock_ollama_success("result"):
            extract_search_query("query", recent_history=history)
        
        assert history == original


class TestProperty8SystemPromptInvariant:
    """
    Property 8: System prompt is invariant to recent_history presence
    
    **Validates: Requirements 7.5**
    
    For any user_message, the system prompt string in the Ollama request SHALL
    be identical whether recent_history is None, an empty list, or a non-empty
    list.
    """
    
    @given(
        st.text(min_size=1, max_size=50),
        st.lists(
            st.fixed_dictionaries({
                "role": st.sampled_from(["user", "assistant"]),
                "content": st.text(min_size=1, max_size=50)
            }),
            min_size=1,
            max_size=10
        )
    )
    @settings(max_examples=100)
    def test_system_prompt_invariant(self, user_message, history):
        """Test that system prompt is identical with and without history."""
        with capture_ollama_request(user_message, recent_history=None) as captured_none:
            system_prompt_none = captured_none["messages"][0]["content"]
        
        with capture_ollama_request(user_message, recent_history=history) as captured_hist:
            system_prompt_hist = captured_hist["messages"][0]["content"]
        
        assert system_prompt_none == system_prompt_hist


class TestProperty9NoneAndEmptyEquivalent:
    """
    Property 9: None and empty list are equivalent
    
    **Validates: Requirements 7.6**
    
    For any user_message, calling extract_search_query(user_message,
    recent_history=None) and extract_search_query(user_message,
    recent_history=[]) SHALL produce Ollama request messages arrays with
    identical structure.
    """
    
    @given(st.text(min_size=1, max_size=50))
    @settings(max_examples=100)
    def test_none_and_empty_list_equivalent(self, user_message):
        """Test that None and [] produce identical request structures."""
        with capture_ollama_request(user_message, recent_history=None) as captured_none:
            messages_none = captured_none["messages"]
        
        with capture_ollama_request(user_message, recent_history=[]) as captured_empty:
            messages_empty = captured_empty["messages"]
        
        assert messages_none == messages_empty
