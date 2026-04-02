"""Tests for error response conversion.

Covers: HTTP status -> Anthropic error type mapping,
OpenAI error format -> Anthropic error format,
streaming errors (error after 200 response started).

Target module: proxy.converter.errors
Expected entry points:
  convert_error(status_code: int, openai_error: dict|None, message: str|None) -> dict
  map_status_to_error_type(status_code: int) -> str
  format_streaming_error(error_msg: str) -> dict  (SSE error event)
"""

import pytest

from proxy.converter.errors import convert_error, map_status_to_error_type


# ===================================================================
# HTTP status code -> Anthropic error type
# ===================================================================

class TestStatusToErrorType:
    """PLAN.md §1.7: status code -> Anthropic error type mapping table."""

    def test_400_invalid_request(self):
        assert map_status_to_error_type(400) == "invalid_request_error"

    def test_401_authentication(self):
        assert map_status_to_error_type(401) == "authentication_error"

    def test_403_permission(self):
        assert map_status_to_error_type(403) == "permission_error"

    def test_404_not_found(self):
        assert map_status_to_error_type(404) == "not_found_error"

    def test_429_rate_limit(self):
        assert map_status_to_error_type(429) == "rate_limit_error"

    def test_500_api_error(self):
        assert map_status_to_error_type(500) == "api_error"

    def test_502_api_error(self):
        assert map_status_to_error_type(502) == "api_error"

    def test_503_api_error(self):
        assert map_status_to_error_type(503) == "api_error"

    def test_unknown_status_defaults_to_api_error(self):
        assert map_status_to_error_type(418) == "api_error"

    def test_422_invalid_request(self):
        """422 Unprocessable Entity is common for validation errors."""
        result = map_status_to_error_type(422)
        assert result in ("invalid_request_error", "api_error")


# ===================================================================
# OpenAI error format -> Anthropic error format
# ===================================================================

class TestConvertError:
    """PLAN.md §1.7:
    OpenAI: {"error": {"message": "...", "type": "...", "code": "..."}}
    Anthropic: {"type": "error", "error": {"type": "...", "message": "..."}}
    """

    def test_basic_error_conversion(self):
        openai_error = {
            "error": {
                "message": "Invalid API key provided.",
                "type": "invalid_request_error",
                "code": "invalid_api_key",
            }
        }
        result = convert_error(401, openai_error)
        assert result["type"] == "error"
        assert result["error"]["type"] == "authentication_error"
        assert "Invalid API key" in result["error"]["message"]

    def test_rate_limit_error(self):
        openai_error = {
            "error": {
                "message": "Rate limit exceeded. Please retry after 30s.",
                "type": "rate_limit_error",
                "code": "rate_limit_exceeded",
            }
        }
        result = convert_error(429, openai_error)
        assert result["type"] == "error"
        assert result["error"]["type"] == "rate_limit_error"
        assert "Rate limit" in result["error"]["message"]

    def test_server_error(self):
        openai_error = {
            "error": {
                "message": "Internal server error.",
                "type": "server_error",
                "code": None,
            }
        }
        result = convert_error(500, openai_error)
        assert result["type"] == "error"
        assert result["error"]["type"] == "api_error"

    def test_none_openai_error_uses_message(self):
        result = convert_error(503, None, message="Service unavailable")
        assert result["type"] == "error"
        assert result["error"]["type"] == "api_error"
        assert "Service unavailable" in result["error"]["message"]

    def test_no_message_at_all(self):
        result = convert_error(500, None)
        assert result["type"] == "error"
        assert result["error"]["type"] == "api_error"
        assert isinstance(result["error"]["message"], str)
        assert len(result["error"]["message"]) > 0

    def test_model_not_found(self):
        openai_error = {
            "error": {
                "message": "The model 'xyz' does not exist.",
                "type": "invalid_request_error",
                "code": "model_not_found",
            }
        }
        result = convert_error(404, openai_error)
        assert result["type"] == "error"
        assert result["error"]["type"] == "not_found_error"

    def test_context_length_exceeded(self):
        openai_error = {
            "error": {
                "message": "This model's maximum context length is 8192 tokens.",
                "type": "invalid_request_error",
                "code": "context_length_exceeded",
            }
        }
        result = convert_error(400, openai_error)
        assert result["type"] == "error"
        assert result["error"]["type"] == "invalid_request_error"
        assert "context" in result["error"]["message"].lower() or "8192" in result["error"]["message"]


# ===================================================================
# Streaming errors
# ===================================================================

class TestStreamingError:
    """PLAN.md §1.7: Streaming errors (SSE after 200 response started):
    emit error event then close stream."""

    def test_streaming_error_event_format(self):
        from proxy.converter.errors import format_streaming_error

        result = format_streaming_error("Backend connection dropped")
        assert result["event"] == "error"
        assert result["data"]["type"] == "error"
        assert result["data"]["error"]["type"] == "api_error"
        assert "Backend connection dropped" in result["data"]["error"]["message"]

    def test_streaming_error_custom_type(self):
        from proxy.converter.errors import format_streaming_error

        result = format_streaming_error(
            "Rate limit hit mid-stream",
            error_type="rate_limit_error",
        )
        assert result["data"]["error"]["type"] == "rate_limit_error"


# ===================================================================
# Edge cases
# ===================================================================

class TestErrorEdgeCases:

    def test_nested_openai_error_without_error_key(self):
        """Some backends return errors differently."""
        result = convert_error(400, {"message": "Bad request"})
        assert result["type"] == "error"

    def test_empty_error_object(self):
        result = convert_error(500, {})
        assert result["type"] == "error"
        assert result["error"]["type"] == "api_error"

    def test_string_error_body(self):
        """Backend returns plain text error."""
        result = convert_error(502, None, message="Bad Gateway")
        assert result["type"] == "error"
        assert "Bad Gateway" in result["error"]["message"]
