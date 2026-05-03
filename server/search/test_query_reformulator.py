"""
Unit tests for query_reformulator module.

Tests query extraction, Japanese detection, fallback behavior, and history handling.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import httpx
import logging

from server.search.query_reformulator import (
    extract_search_query,
    _is_japanese,
    _build_system_prompt,
    OLLAMA_BASE_URL,
    REFORMULATOR_MODEL,
)


class TestIsJapanese:
    """Test suite for _is_japanese helper function."""
    
    def test_hiragana_detected(self):
        """Test that hiragana characters are detected as Japanese."""
        assert _is_japanese("こんにちは") is True
    
    def test_katakana_detected(self):
        """Test that katakana characters are detected as Japanese."""
        assert _is_japanese("カタカナ") is True
    
    def test_kanji_detected(self):
        """Test that kanji characters are detected as Japanese."""
        assert _is_japanese("日本語") is True
    
    def test_mixed_japanese_english(self):
        """Test that mixed Japanese-English text is detected as Japanese."""
        assert _is_japanese("Hello 世界") is True
    
    def test_english_only(self):
        """Test that English-only text is not detected as Japanese."""
        assert _is_japanese("Hello world") is False
    
    def test_empty_string(self):
        """Test that empty string is not detected as Japanese."""
        assert _is_japanese("") is False
    
    def test_numbers_only(self):
        """Test that numbers-only text is not detected as Japanese."""
        assert _is_japanese("12345") is False


class TestBuildSystemPrompt:
    """Test suite for _build_system_prompt helper function."""
    
    def test_japanese_prompt_contains_translate(self):
        """Test that Japanese prompt contains translation instruction."""
        prompt = _build_system_prompt(is_japanese=True)
        assert "translate" in prompt.lower()
        assert "japanese" in prompt.lower()
        assert "english" in prompt.lower()
    
    def test_english_prompt_no_translate(self):
        """Test that English prompt does not contain translation instruction."""
        prompt = _build_system_prompt(is_japanese=False)
        assert "translate" not in prompt.lower()
    
    def test_both_prompts_contain_core_instructions(self):
        """Test that both prompts contain core extraction instructions."""
        japanese_prompt = _build_system_prompt(is_japanese=True)
        english_prompt = _build_system_prompt(is_japanese=False)
        
        for prompt in [japanese_prompt, english_prompt]:
            assert "3 to 6 words" in prompt
            assert "search query" in prompt.lower()
            assert "no explanation" in prompt.lower()
            assert "no punctuation" in prompt.lower()
            assert "no quotes" in prompt.lower()


class TestExtractSearchQuery:
    """Test suite for extract_search_query function."""
    
    def test_successful_english_reformulation(self):
        """Test successful reformulation of English query."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "  tokyo weather forecast  "}}]
        }
        mock_response.raise_for_status = Mock()
        
        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = mock_response
            
            result = extract_search_query("What's the weather like in Tokyo?")
            
            assert result == "tokyo weather forecast"
    
    def test_successful_japanese_reformulation(self):
        """Test successful reformulation of Japanese query."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "tokyo weather"}}]
        }
        mock_response.raise_for_status = Mock()
        
        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = mock_response
            
            result = extract_search_query("東京の天気はどうですか？")
            
            assert result == "tokyo weather"
    
    def test_japanese_query_uses_translation_prompt(self):
        """Test that Japanese query triggers translation system prompt."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "tokyo weather"}}]
        }
        mock_response.raise_for_status = Mock()
        
        with patch("httpx.Client") as mock_client:
            mock_post = mock_client.return_value.__enter__.return_value.post
            mock_post.return_value = mock_response
            
            extract_search_query("東京の天気")
            
            # Check that the request was made
            assert mock_post.called
            request_body = mock_post.call_args[1]["json"]
            system_msg = request_body["messages"][0]["content"]
            
            assert "translate" in system_msg.lower()
    
    def test_connect_error_fallback(self):
        """Test that ConnectError triggers fallback to original input."""
        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.side_effect = httpx.ConnectError("Connection failed")
            
            result = extract_search_query("What's the weather?")
            
            assert result == "What's the weather?"
    
    def test_timeout_exception_fallback(self):
        """Test that TimeoutException triggers fallback to original input."""
        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.side_effect = httpx.TimeoutException("Timeout")
            
            result = extract_search_query("What's the weather?")
            
            assert result == "What's the weather?"
    
    def test_http_status_error_fallback(self):
        """Test that non-2xx HTTP status triggers fallback."""
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500 Server Error", request=Mock(), response=Mock()
        )
        
        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = mock_response
            
            result = extract_search_query("What's the weather?")
            
            assert result == "What's the weather?"
    
    def test_malformed_json_fallback(self):
        """Test that malformed JSON response triggers fallback."""
        mock_response = Mock()
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_response.raise_for_status = Mock()
        
        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = mock_response
            
            result = extract_search_query("What's the weather?")
            
            assert result == "What's the weather?"
    
    def test_missing_key_fallback(self):
        """Test that missing key in response triggers fallback."""
        mock_response = Mock()
        mock_response.json.return_value = {"wrong_key": "value"}
        mock_response.raise_for_status = Mock()
        
        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = mock_response
            
            result = extract_search_query("What's the weather?")
            
            assert result == "What's the weather?"
    
    def test_none_history_and_empty_list_equivalent(self):
        """Test that recent_history=None and recent_history=[] produce identical requests."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "message": {"content": "test query"}
        }
        mock_response.raise_for_status = Mock()
        
        with patch("httpx.Client") as mock_client:
            mock_post = mock_client.return_value.__enter__.return_value.post
            mock_post.return_value = mock_response
            
            # Call with None
            extract_search_query("test", recent_history=None)
            request_none = mock_post.call_args[1]["json"]
            
            # Call with empty list
            extract_search_query("test", recent_history=[])
            request_empty = mock_post.call_args[1]["json"]
            
            assert request_none["messages"] == request_empty["messages"]
    
    def test_history_sliced_to_six(self):
        """Test that recent_history with 10 entries is sliced to 6 in the request."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "message": {"content": "test query"}
        }
        mock_response.raise_for_status = Mock()
        
        # Create 10 history entries
        long_history = [
            {"role": "user", "content": f"message {i}"}
            for i in range(10)
        ]
        
        with patch("httpx.Client") as mock_client:
            mock_post = mock_client.return_value.__enter__.return_value.post
            mock_post.return_value = mock_response
            
            extract_search_query("test", recent_history=long_history)
            
            request_body = mock_post.call_args[1]["json"]
            messages = request_body["messages"]
            
            # messages = [system] + [history...] + [current_user]
            # So history messages are messages[1:-1]
            history_messages = messages[1:-1]
            
            assert len(history_messages) == 6
    
    def test_current_message_is_last(self):
        """Test that current user message is always the last element in messages."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "message": {"content": "test query"}
        }
        mock_response.raise_for_status = Mock()
        
        history = [
            {"role": "user", "content": "previous message"},
            {"role": "assistant", "content": "previous response"}
        ]
        
        with patch("httpx.Client") as mock_client:
            mock_post = mock_client.return_value.__enter__.return_value.post
            mock_post.return_value = mock_response
            
            user_message = "current message"
            extract_search_query(user_message, recent_history=history)
            
            request_body = mock_post.call_args[1]["json"]
            messages = request_body["messages"]
            
            last_msg = messages[-1]
            assert last_msg["role"] == "user"
            assert last_msg["content"] == user_message
    
    def test_ollama_base_url_default(self):
        """Test that OLLAMA_BASE_URL defaults to http://localhost:11434."""
        assert OLLAMA_BASE_URL == "http://localhost:11434"
    
    def test_reformulator_model_default(self):
        """Test that REFORMULATOR_MODEL defaults to qwen2.5:3b."""
        assert REFORMULATOR_MODEL == "qwen2.5:3b"
    
    def test_request_body_structure(self):
        """Test that request body contains correct structure and parameters."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "test query"}}]
        }
        mock_response.raise_for_status = Mock()
        
        with patch("httpx.Client") as mock_client:
            mock_post = mock_client.return_value.__enter__.return_value.post
            mock_post.return_value = mock_response
            
            extract_search_query("test")
            
            # Check URL
            call_args = mock_post.call_args
            assert call_args[0][0] == f"{OLLAMA_BASE_URL}/v1/chat/completions"
            
            # Check request body (OpenAI-compatible format)
            request_body = call_args[1]["json"]
            assert request_body["model"] == REFORMULATOR_MODEL
            assert request_body["stream"] is False
            assert request_body["temperature"] == 0
            assert request_body["max_tokens"] == 32
    
    def test_warning_logged_on_exception(self):
        """Test that WARNING is logged on any exception."""
        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.side_effect = Exception("Test error")
            
            with patch("server.search.query_reformulator.logger") as mock_logger:
                result = extract_search_query("test")
                
                assert result == "test"
                assert mock_logger.warning.called
                
                # Check that warning was called with the expected messages
                # The new logging format has multiple warning calls
                warning_calls = [str(call) for call in mock_logger.warning.call_args_list]
                all_warnings = " ".join(warning_calls)
                
                # Check for key phrases in the warning output
                assert "REFORMULATION FAILED" in all_warnings or "FAILED" in all_warnings
                assert "Falling back" in all_warnings or "falling back" in all_warnings
    
    def test_whitespace_stripped_from_response(self):
        """Test that leading and trailing whitespace is stripped from response."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "\n\t  tokyo weather  \n\t"}}]
        }
        mock_response.raise_for_status = Mock()
        
        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = mock_response
            
            result = extract_search_query("test")
            
            assert result == "tokyo weather"
    
    def test_timeout_configuration(self):
        """Test that httpx.Client is configured with 10-second timeout."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "message": {"content": "test"}
        }
        mock_response.raise_for_status = Mock()
        
        with patch("httpx.Client") as mock_client:
            mock_post = mock_client.return_value.__enter__.return_value.post
            mock_post.return_value = mock_response
            
            extract_search_query("test")
            
            # Check that Client was called with timeout
            client_call = mock_client.call_args
            timeout_arg = client_call[1]["timeout"]
            
            # Should be httpx.Timeout(10.0)
            assert isinstance(timeout_arg, httpx.Timeout) or timeout_arg == httpx.Timeout(10.0)
    
    def test_history_not_mutated(self):
        """Test that recent_history list is not mutated by the function."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "message": {"content": "test"}
        }
        mock_response.raise_for_status = Mock()
        
        original_history = [
            {"role": "user", "content": "message 1"},
            {"role": "assistant", "content": "response 1"}
        ]
        history_copy = original_history.copy()
        
        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = mock_response
            
            extract_search_query("test", recent_history=original_history)
            
            assert original_history == history_copy
    
    def test_system_prompt_invariant_to_history(self):
        """Test that system prompt is identical with and without history."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "message": {"content": "test"}
        }
        mock_response.raise_for_status = Mock()
        
        history = [{"role": "user", "content": "previous"}]
        
        with patch("httpx.Client") as mock_client:
            mock_post = mock_client.return_value.__enter__.return_value.post
            mock_post.return_value = mock_response
            
            # Call without history
            extract_search_query("test", recent_history=None)
            request_none = mock_post.call_args[1]["json"]
            system_prompt_none = request_none["messages"][0]["content"]
            
            # Call with history
            extract_search_query("test", recent_history=history)
            request_hist = mock_post.call_args[1]["json"]
            system_prompt_hist = request_hist["messages"][0]["content"]
            
            assert system_prompt_none == system_prompt_hist
