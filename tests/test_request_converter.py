"""Tests for Anthropic -> OpenAI request conversion.

Covers: system prompt handling, parameter mapping, field stripping,
content block conversion, stream_options injection.

Target module: proxy.converter.request
Expected entry point: convert_request(anthropic_body: dict, model_map: dict) -> dict
"""

import pytest

from proxy.converter.request import convert_request


# ===================================================================
# System prompt handling
# ===================================================================

class TestSystemPrompt:
    """PLAN.md §1.2: system (string or content block array) -> first message role:system."""

    def test_string_system_becomes_first_message(self, anthropic_basic_text, model_map):
        result = convert_request(anthropic_basic_text, model_map)
        assert result["messages"][0]["role"] == "system"
        assert result["messages"][0]["content"] == "You are a helpful assistant."

    def test_array_system_flattened_and_cache_control_stripped(self, anthropic_system_array, model_map):
        result = convert_request(anthropic_system_array, model_map)
        sys_msg = result["messages"][0]
        assert sys_msg["role"] == "system"
        # Two text blocks joined (newline or space separated)
        assert "You are a coding assistant." in sys_msg["content"]
        assert "Always respond in JSON." in sys_msg["content"]
        # cache_control must not leak through
        assert "cache_control" not in str(sys_msg)

    def test_no_system_field_means_no_system_message(self, model_map):
        body = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 256,
            "messages": [{"role": "user", "content": "Hi"}],
        }
        result = convert_request(body, model_map)
        assert result["messages"][0]["role"] != "system"

    def test_empty_string_system_is_omitted(self, model_map):
        body = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 256,
            "system": "",
            "messages": [{"role": "user", "content": "Hi"}],
        }
        result = convert_request(body, model_map)
        # Either no system message or empty content — both acceptable
        first = result["messages"][0]
        if first["role"] == "system":
            assert first["content"] == ""
        else:
            assert first["role"] == "user"


# ===================================================================
# Parameter mapping
# ===================================================================

class TestParameterMapping:
    """PLAN.md §1.2 parameter mapping table."""

    def test_model_name_mapped(self, anthropic_basic_text, model_map):
        result = convert_request(anthropic_basic_text, model_map)
        assert result["model"] == "kimi-2.5"

    def test_max_tokens_direct(self, anthropic_basic_text, model_map):
        result = convert_request(anthropic_basic_text, model_map)
        assert result["max_tokens"] == 1024

    def test_temperature_and_top_p_direct(self, anthropic_full_params, model_map):
        result = convert_request(anthropic_full_params, model_map)
        assert result["temperature"] == 0.7
        assert result["top_p"] == 0.9

    def test_stop_sequences_renamed_to_stop(self, anthropic_full_params, model_map):
        result = convert_request(anthropic_full_params, model_map)
        assert "stop_sequences" not in result
        assert result["stop"] == ["\n\nHuman:", "\n\nAssistant:"]

    def test_stream_flag_preserved(self, anthropic_full_params, model_map):
        result = convert_request(anthropic_full_params, model_map)
        assert result["stream"] is True


# ===================================================================
# Stripped fields
# ===================================================================

class TestStrippedFields:
    """Fields that must NOT appear in the OpenAI request."""

    def test_top_k_stripped(self, anthropic_full_params, model_map):
        result = convert_request(anthropic_full_params, model_map)
        assert "top_k" not in result

    def test_metadata_stripped(self, anthropic_full_params, model_map):
        result = convert_request(anthropic_full_params, model_map)
        assert "metadata" not in result

    def test_thinking_stripped(self, model_map):
        body = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 1024,
            "thinking": {"budget_tokens": 500},
            "messages": [{"role": "user", "content": "Think hard."}],
        }
        result = convert_request(body, model_map)
        assert "thinking" not in result

    def test_cache_control_stripped_from_messages(self, model_map):
        body = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 256,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Hello",
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                }
            ],
        }
        result = convert_request(body, model_map)
        # Deep check: no cache_control anywhere in result
        assert "cache_control" not in str(result)


# ===================================================================
# stream_options injection
# ===================================================================

class TestStreamOptions:
    """PLAN.md §1.2: when stream=true, add stream_options.include_usage=true."""

    def test_stream_options_injected_when_streaming(self, anthropic_full_params, model_map):
        result = convert_request(anthropic_full_params, model_map)
        assert result.get("stream_options", {}).get("include_usage") is True

    def test_no_stream_options_when_not_streaming(self, anthropic_basic_text, model_map):
        result = convert_request(anthropic_basic_text, model_map)
        # stream not set -> stream_options should be absent or stream=false
        assert result.get("stream") in (None, False) or "stream_options" not in result


# ===================================================================
# Content block conversion (text, image)
# ===================================================================

class TestContentBlockConversion:
    """PLAN.md §1.4 content block conversion table."""

    def test_plain_string_content_passthrough(self, anthropic_basic_text, model_map):
        result = convert_request(anthropic_basic_text, model_map)
        # User message with plain string content
        user_msgs = [m for m in result["messages"] if m["role"] == "user"]
        assert len(user_msgs) >= 1
        # Content should be a string or list with text
        content = user_msgs[0]["content"]
        if isinstance(content, str):
            assert content == "Hello, world!"
        else:
            texts = [b["text"] for b in content if b.get("type") == "text"]
            assert "Hello, world!" in texts

    def test_image_base64_converted_to_data_uri(self, anthropic_image_base64, model_map):
        result = convert_request(anthropic_image_base64, model_map)
        user_msgs = [m for m in result["messages"] if m["role"] == "user"]
        content = user_msgs[0]["content"]
        assert isinstance(content, list)

        image_parts = [b for b in content if b.get("type") == "image_url"]
        assert len(image_parts) == 1
        url = image_parts[0]["image_url"]["url"]
        assert url.startswith("data:image/png;base64,")
        assert "iVBORw0KGgo" in url

    def test_image_url_passthrough(self, anthropic_image_url, model_map):
        result = convert_request(anthropic_image_url, model_map)
        user_msgs = [m for m in result["messages"] if m["role"] == "user"]
        content = user_msgs[0]["content"]
        assert isinstance(content, list)

        image_parts = [b for b in content if b.get("type") == "image_url"]
        assert len(image_parts) == 1
        assert image_parts[0]["image_url"]["url"] == "https://example.com/photo.jpg"

    def test_text_block_converted(self, anthropic_image_base64, model_map):
        result = convert_request(anthropic_image_base64, model_map)
        user_msgs = [m for m in result["messages"] if m["role"] == "user"]
        content = user_msgs[0]["content"]
        text_parts = [b for b in content if b.get("type") == "text"]
        assert len(text_parts) >= 1
        assert text_parts[0]["text"] == "What is in this image?"


# ===================================================================
# Message role conversion
# ===================================================================

class TestMessageRoles:
    """Basic role mapping: user->user, assistant->assistant."""

    def test_user_role_preserved(self, anthropic_basic_text, model_map):
        result = convert_request(anthropic_basic_text, model_map)
        user_msgs = [m for m in result["messages"] if m["role"] == "user"]
        assert len(user_msgs) >= 1

    def test_assistant_role_preserved(self, model_map):
        body = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 256,
            "messages": [
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello!"},
                {"role": "user", "content": "How are you?"},
            ],
        }
        result = convert_request(body, model_map)
        non_system = [m for m in result["messages"] if m["role"] != "system"]
        assert non_system[0]["role"] == "user"
        assert non_system[1]["role"] == "assistant"
        assert non_system[2]["role"] == "user"


# ===================================================================
# Model not in map → passthrough
# ===================================================================

class TestUnmappedModel:

    def test_unmapped_model_passes_through(self):
        body = {
            "model": "unknown-model-xyz",
            "max_tokens": 100,
            "messages": [{"role": "user", "content": "Hi"}],
        }
        result = convert_request(body, {})
        assert result["model"] == "unknown-model-xyz"


# ===================================================================
# Assistant tool_use in history → tool_calls format
# ===================================================================

class TestAssistantToolUseConversion:
    """Assistant messages with tool_use content blocks must be converted
    to OpenAI tool_calls format in the message history."""

    def test_assistant_tool_use_becomes_tool_calls(self, anthropic_tool_result, model_map):
        result = convert_request(anthropic_tool_result, model_map)
        assistant_msgs = [m for m in result["messages"] if m["role"] == "assistant"]
        assert len(assistant_msgs) >= 1
        a = assistant_msgs[0]
        assert "tool_calls" in a
        tc = a["tool_calls"][0]
        assert tc["type"] == "function"
        assert tc["function"]["name"] == "get_weather"
        # ID should be translated: toolu_ -> call_ prefix
        assert tc["id"].startswith("call_")
