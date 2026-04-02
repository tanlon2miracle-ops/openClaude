"""Tests for OpenAI -> Anthropic response conversion.

Covers: text response, ID format, stop_reason mapping, usage mapping,
cache token fields, tool_calls -> tool_use blocks.

Target module: proxy.converter.response
Expected entry point: convert_response(openai_body: dict, model_alias: str) -> dict
"""

import json

import pytest

from proxy.converter.response import convert_response


# ===================================================================
# Basic text response
# ===================================================================

class TestBasicTextResponse:

    def test_type_is_message(self, openai_basic_text):
        result = convert_response(openai_basic_text, "claude-sonnet-4-20250514")
        assert result["type"] == "message"

    def test_role_is_assistant(self, openai_basic_text):
        result = convert_response(openai_basic_text, "claude-sonnet-4-20250514")
        assert result["role"] == "assistant"

    def test_content_is_text_block(self, openai_basic_text):
        result = convert_response(openai_basic_text, "claude-sonnet-4-20250514")
        assert len(result["content"]) >= 1
        block = result["content"][0]
        assert block["type"] == "text"
        assert block["text"] == "Hello! How can I help you today?"

    def test_model_uses_alias(self, openai_basic_text):
        result = convert_response(openai_basic_text, "claude-sonnet-4-20250514")
        assert result["model"] == "claude-sonnet-4-20250514"


# ===================================================================
# ID format
# ===================================================================

class TestIdFormat:
    """PLAN.md: generate msg_ prefix IDs, never pass through chatcmpl-."""

    def test_message_id_has_msg_prefix(self, openai_basic_text):
        result = convert_response(openai_basic_text, "claude-sonnet-4-20250514")
        assert result["id"].startswith("msg_")
        assert "chatcmpl" not in result["id"]

    def test_message_id_is_unique(self, openai_basic_text):
        r1 = convert_response(openai_basic_text, "claude-sonnet-4-20250514")
        r2 = convert_response(openai_basic_text, "claude-sonnet-4-20250514")
        assert r1["id"] != r2["id"]


# ===================================================================
# stop_reason mapping
# ===================================================================

class TestStopReasonMapping:
    """PLAN.md §1.5: stop->end_turn, length->max_tokens, tool_calls->tool_use."""

    def test_stop_maps_to_end_turn(self, openai_basic_text):
        result = convert_response(openai_basic_text, "claude-sonnet-4-20250514")
        assert result["stop_reason"] == "end_turn"

    def test_length_maps_to_max_tokens(self, openai_length_stop):
        result = convert_response(openai_length_stop, "claude-sonnet-4-20250514")
        assert result["stop_reason"] == "max_tokens"

    def test_tool_calls_maps_to_tool_use(self, openai_tool_call):
        result = convert_response(openai_tool_call, "claude-sonnet-4-20250514")
        assert result["stop_reason"] == "tool_use"

    def test_stop_with_stop_sequence_configured(self, openai_basic_text):
        """When stop_sequences were in the request and finish_reason=stop,
        the stop_reason should be 'end_turn' (default) unless the backend
        indicates a sequence matched. This is the base case."""
        result = convert_response(openai_basic_text, "claude-sonnet-4-20250514")
        assert result["stop_reason"] in ("end_turn", "stop_sequence")


# ===================================================================
# Usage mapping
# ===================================================================

class TestUsageMapping:
    """PLAN.md §1.5: prompt_tokens->input_tokens, completion_tokens->output_tokens."""

    def test_input_tokens(self, openai_basic_text):
        result = convert_response(openai_basic_text, "claude-sonnet-4-20250514")
        assert result["usage"]["input_tokens"] == 25

    def test_output_tokens(self, openai_basic_text):
        result = convert_response(openai_basic_text, "claude-sonnet-4-20250514")
        assert result["usage"]["output_tokens"] == 10

    def test_cache_creation_tokens_zero(self, openai_basic_text):
        result = convert_response(openai_basic_text, "claude-sonnet-4-20250514")
        assert result["usage"]["cache_creation_input_tokens"] == 0

    def test_cache_read_tokens_zero(self, openai_basic_text):
        result = convert_response(openai_basic_text, "claude-sonnet-4-20250514")
        assert result["usage"]["cache_read_input_tokens"] == 0


# ===================================================================
# Tool call response conversion
# ===================================================================

class TestToolCallResponse:
    """PLAN.md §1.5: tool_calls array -> content array of tool_use blocks."""

    def test_tool_use_block_in_content(self, openai_tool_call):
        result = convert_response(openai_tool_call, "claude-sonnet-4-20250514")
        tool_blocks = [b for b in result["content"] if b["type"] == "tool_use"]
        assert len(tool_blocks) == 1

    def test_tool_use_id_has_toolu_prefix(self, openai_tool_call):
        result = convert_response(openai_tool_call, "claude-sonnet-4-20250514")
        tool_block = [b for b in result["content"] if b["type"] == "tool_use"][0]
        assert tool_block["id"].startswith("toolu_")
        assert "call_" not in tool_block["id"]

    def test_tool_use_name_preserved(self, openai_tool_call):
        result = convert_response(openai_tool_call, "claude-sonnet-4-20250514")
        tool_block = [b for b in result["content"] if b["type"] == "tool_use"][0]
        assert tool_block["name"] == "get_weather"

    def test_tool_use_input_is_parsed_object(self, openai_tool_call):
        """arguments is a JSON string in OpenAI; must be parsed to dict for Anthropic."""
        result = convert_response(openai_tool_call, "claude-sonnet-4-20250514")
        tool_block = [b for b in result["content"] if b["type"] == "tool_use"][0]
        assert isinstance(tool_block["input"], dict)
        assert tool_block["input"]["city"] == "Tokyo"

    def test_multiple_tool_calls(self, openai_multi_tool_call):
        result = convert_response(openai_multi_tool_call, "claude-sonnet-4-20250514")
        tool_blocks = [b for b in result["content"] if b["type"] == "tool_use"]
        assert len(tool_blocks) == 2
        names = {b["name"] for b in tool_blocks}
        assert names == {"get_weather"}
        ids = [b["id"] for b in tool_blocks]
        assert ids[0] != ids[1]
        assert all(i.startswith("toolu_") for i in ids)

    def test_mixed_text_and_tool_calls(self, openai_multi_tool_call):
        """When content AND tool_calls both present, content array has text + tool_use blocks."""
        result = convert_response(openai_multi_tool_call, "claude-sonnet-4-20250514")
        types = [b["type"] for b in result["content"]]
        assert "text" in types
        assert "tool_use" in types

    def test_null_content_with_tool_calls(self, openai_tool_call):
        """When content is null but tool_calls present, no text block should appear."""
        result = convert_response(openai_tool_call, "claude-sonnet-4-20250514")
        text_blocks = [b for b in result["content"] if b["type"] == "text"]
        # Either no text blocks, or only empty text block
        for tb in text_blocks:
            if tb["text"]:
                pytest.fail("Non-empty text block found when OpenAI content was null")


# ===================================================================
# Edge cases
# ===================================================================

class TestResponseEdgeCases:

    def test_empty_content_string(self):
        openai_body = {
            "id": "chatcmpl-empty",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": ""},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 5, "completion_tokens": 0, "total_tokens": 5},
        }
        result = convert_response(openai_body, "claude-sonnet-4-20250514")
        assert result["type"] == "message"
        assert result["stop_reason"] == "end_turn"

    def test_missing_usage_defaults_to_zero(self):
        openai_body = {
            "id": "chatcmpl-nousage",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "Hi"},
                "finish_reason": "stop",
            }],
        }
        result = convert_response(openai_body, "claude-sonnet-4-20250514")
        assert result["usage"]["input_tokens"] >= 0
        assert result["usage"]["output_tokens"] >= 0

    def test_malformed_tool_arguments_handled(self):
        """If arguments is not valid JSON, should handle gracefully."""
        openai_body = {
            "id": "chatcmpl-badjson",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "call_bad",
                        "type": "function",
                        "function": {
                            "name": "test_fn",
                            "arguments": "{invalid json",
                        },
                    }],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
        }
        # Should not raise; may wrap the raw string or return empty dict
        result = convert_response(openai_body, "claude-sonnet-4-20250514")
        tool_blocks = [b for b in result["content"] if b["type"] == "tool_use"]
        assert len(tool_blocks) == 1
