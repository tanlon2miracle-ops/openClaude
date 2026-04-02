"""Tests for tool calling translation.

Covers: tool definition conversion, tool_choice mapping,
disable_parallel_tool_use inversion, tool_result splitting,
tool call ID format, arguments parsing.

Target module: proxy.converter.tools
Expected entry points:
  convert_tools(anthropic_tools: list[dict]) -> list[dict]
  convert_tool_choice(anthropic_choice: dict|str, tools: list[dict]|None) -> str|dict
  convert_tool_result_messages(anthropic_messages: list[dict]) -> list[dict]
  convert_parallel_tool_use(body: dict) -> dict  (or handled inside convert_request)
"""

import pytest

from proxy.converter.tools import (
    convert_tools,
    convert_tool_choice,
    convert_tool_result_messages,
)


# ===================================================================
# Tool definition conversion
# ===================================================================

class TestToolDefinition:
    """PLAN.md §1.3: input_schema -> parameters, wrapped in function object."""

    def test_basic_tool_structure(self):
        anthropic_tools = [
            {
                "name": "get_weather",
                "description": "Get the weather.",
                "input_schema": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            }
        ]
        result = convert_tools(anthropic_tools)
        assert len(result) == 1
        tool = result[0]
        assert tool["type"] == "function"
        assert tool["function"]["name"] == "get_weather"
        assert tool["function"]["description"] == "Get the weather."
        assert tool["function"]["parameters"]["type"] == "object"
        assert "city" in tool["function"]["parameters"]["properties"]

    def test_multiple_tools(self):
        anthropic_tools = [
            {
                "name": "tool_a",
                "description": "A",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "tool_b",
                "description": "B",
                "input_schema": {"type": "object", "properties": {}},
            },
        ]
        result = convert_tools(anthropic_tools)
        assert len(result) == 2
        assert result[0]["function"]["name"] == "tool_a"
        assert result[1]["function"]["name"] == "tool_b"

    def test_no_description_field(self):
        """Some tools might not have a description."""
        anthropic_tools = [
            {
                "name": "silent_tool",
                "input_schema": {"type": "object", "properties": {}},
            }
        ]
        result = convert_tools(anthropic_tools)
        tool = result[0]
        assert tool["function"]["name"] == "silent_tool"
        # description should be empty string or absent
        assert tool["function"].get("description", "") == "" or "description" not in tool["function"]

    def test_empty_tools_list(self):
        result = convert_tools([])
        assert result == []

    def test_complex_schema_preserved(self):
        schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "filters": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "field": {"type": "string"},
                            "op": {"type": "string", "enum": ["eq", "neq", "gt", "lt"]},
                            "value": {},
                        },
                    },
                },
            },
            "required": ["query"],
        }
        anthropic_tools = [
            {"name": "search", "description": "Search", "input_schema": schema}
        ]
        result = convert_tools(anthropic_tools)
        assert result[0]["function"]["parameters"] == schema


# ===================================================================
# tool_choice mapping
# ===================================================================

class TestToolChoiceMapping:
    """PLAN.md §1.3: auto->"auto", any->"required", none->"none", tool->function spec."""

    def test_auto(self):
        result = convert_tool_choice({"type": "auto"})
        assert result == "auto"

    def test_any_to_required(self):
        """Critical pitfall #1: Anthropic 'any' -> OpenAI 'required'."""
        result = convert_tool_choice({"type": "any"})
        assert result == "required"

    def test_none(self):
        result = convert_tool_choice({"type": "none"})
        assert result == "none"

    def test_specific_tool(self):
        result = convert_tool_choice({"type": "tool", "name": "get_weather"})
        assert isinstance(result, dict)
        assert result["type"] == "function"
        assert result["function"]["name"] == "get_weather"

    def test_string_auto_passthrough(self):
        """Some callers might pass just a string."""
        result = convert_tool_choice("auto")
        assert result == "auto"

    def test_none_input(self):
        """If tool_choice is not specified (None), return None or "auto"."""
        result = convert_tool_choice(None)
        assert result is None or result == "auto"


# ===================================================================
# disable_parallel_tool_use -> parallel_tool_calls inversion
# ===================================================================

class TestParallelToolUse:
    """PLAN.md §1.3: disable_parallel_tool_use: true -> parallel_tool_calls: false."""

    def test_disable_true_becomes_false(self):
        anthropic_choice = {"type": "auto", "disable_parallel_tool_use": True}
        # The converter should extract and invert this
        result = convert_tool_choice(anthropic_choice)
        # The parallel_tool_calls flag is typically set on the request body,
        # not in tool_choice itself. Test that the choice value is still correct.
        assert result == "auto"

    def test_disable_false_becomes_true(self):
        anthropic_choice = {"type": "auto", "disable_parallel_tool_use": False}
        result = convert_tool_choice(anthropic_choice)
        assert result == "auto"


class TestParallelToolCallsExtraction:
    """Test that disable_parallel_tool_use is extracted and inverted at the request level."""

    def test_disable_parallel_extracted_from_tool_choice(self):
        """The request converter should set parallel_tool_calls based on
        disable_parallel_tool_use in tool_choice."""
        from proxy.converter.request import convert_request

        body = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": "Hi"}],
            "tools": [
                {
                    "name": "test",
                    "description": "Test",
                    "input_schema": {"type": "object", "properties": {}},
                }
            ],
            "tool_choice": {"type": "auto", "disable_parallel_tool_use": True},
        }
        model_map = {"claude-sonnet-4-20250514": "kimi-2.5"}
        result = convert_request(body, model_map)
        assert result.get("parallel_tool_calls") is False

    def test_no_disable_parallel_means_absent_or_true(self):
        from proxy.converter.request import convert_request

        body = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": "Hi"}],
            "tools": [
                {
                    "name": "test",
                    "description": "Test",
                    "input_schema": {"type": "object", "properties": {}},
                }
            ],
            "tool_choice": {"type": "auto"},
        }
        model_map = {"claude-sonnet-4-20250514": "kimi-2.5"}
        result = convert_request(body, model_map)
        # Either absent (default true) or explicitly true
        assert result.get("parallel_tool_calls") in (None, True)


# ===================================================================
# tool_result conversion (role-level structural change)
# ===================================================================

class TestToolResultConversion:
    """PLAN.md §1.3: user message with tool_result -> separate role:tool messages."""

    def test_simple_tool_result(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_abc123",
                        "content": "72F and sunny",
                    }
                ],
            }
        ]
        result = convert_tool_result_messages(messages)
        tool_msgs = [m for m in result if m["role"] == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["content"] == "72F and sunny"
        # ID must be translated: toolu_ -> call_
        assert tool_msgs[0]["tool_call_id"].startswith("call_")

    def test_mixed_text_and_tool_result_split(self):
        """Text blocks stay as user, tool_results become role:tool.
        PLAN.md §1.3: preserve ordering."""
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Here's the result:"},
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_abc123",
                        "content": "72F and sunny",
                    },
                    {"type": "text", "text": "What do you think?"},
                ],
            }
        ]
        result = convert_tool_result_messages(messages)
        # Should produce: user("Here's...") -> tool(...) -> user("What do...")
        assert len(result) >= 3
        roles = [m["role"] for m in result]
        assert "tool" in roles
        assert "user" in roles

    def test_multiple_tool_results(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_aaa",
                        "content": "Result A",
                    },
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_bbb",
                        "content": "Result B",
                    },
                ],
            }
        ]
        result = convert_tool_result_messages(messages)
        tool_msgs = [m for m in result if m["role"] == "tool"]
        assert len(tool_msgs) == 2

    def test_regular_user_message_unchanged(self):
        messages = [
            {"role": "user", "content": "Hello!"},
        ]
        result = convert_tool_result_messages(messages)
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "Hello!"

    def test_tool_result_with_array_content(self):
        """tool_result content can be an array of content blocks."""
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_xyz",
                        "content": [
                            {"type": "text", "text": "Line 1"},
                            {"type": "text", "text": "Line 2"},
                        ],
                    }
                ],
            }
        ]
        result = convert_tool_result_messages(messages)
        tool_msgs = [m for m in result if m["role"] == "tool"]
        assert len(tool_msgs) == 1
        # Content should be stringified or joined
        content = tool_msgs[0]["content"]
        assert isinstance(content, str)
        assert "Line 1" in content
        assert "Line 2" in content

    def test_tool_result_is_error(self):
        """tool_result can have is_error=true; should still produce role:tool."""
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_err",
                        "content": "Error: file not found",
                        "is_error": True,
                    }
                ],
            }
        ]
        result = convert_tool_result_messages(messages)
        tool_msgs = [m for m in result if m["role"] == "tool"]
        assert len(tool_msgs) == 1
        assert "Error" in tool_msgs[0]["content"]


# ===================================================================
# Tool call ID format translation
# ===================================================================

class TestToolCallIdFormat:
    """PLAN.md pitfall #3: Claude Code may validate toolu_ prefix.
    call_ <-> toolu_ translation must be bidirectional."""

    def test_toolu_to_call_in_request(self):
        """In request: toolu_abc -> call_abc (for tool_result -> role:tool)."""
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_abc123def",
                        "content": "ok",
                    }
                ],
            }
        ]
        result = convert_tool_result_messages(messages)
        tool_msg = [m for m in result if m["role"] == "tool"][0]
        assert tool_msg["tool_call_id"].startswith("call_")
        # The suffix after the prefix should be preserved
        assert "abc123def" in tool_msg["tool_call_id"]

    def test_call_to_toolu_in_response(self):
        """In response: call_xxx -> toolu_xxx (tested in test_response_converter)."""
        from proxy.converter.response import convert_response

        openai_body = {
            "id": "chatcmpl-test",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "call_myid123",
                        "type": "function",
                        "function": {"name": "fn", "arguments": "{}"},
                    }],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        result = convert_response(openai_body, "claude-sonnet-4-20250514")
        tool_block = result["content"][0]
        assert tool_block["id"].startswith("toolu_")
        assert "myid123" in tool_block["id"]
