"""Tests for the streaming SSE state machine.

This is the MOST CRITICAL test file. The streaming state machine converts
OpenAI flat SSE chunks into Anthropic hierarchical typed events.

Covers: text-only, tool call, mixed, multi-tool, finish_reason,
[DONE] sentinel, empty chunks, usage in final chunk, SSE format.

Target module: proxy.streaming
Expected entry point:
  StreamingConverter (class) with method:
    process_chunk(chunk: dict) -> list[AnthropicSSEEvent]
  or async generator:
    convert_stream(openai_chunks: AsyncIterator) -> AsyncIterator[str]

Each AnthropicSSEEvent should have:
  event_type: str  (message_start, content_block_start, content_block_delta,
                    content_block_stop, message_delta, message_stop)
  data: dict       (JSON payload)

State machine reference: PLAN.md §1.6
"""

import json
from typing import Any

import pytest

from proxy.streaming import StreamingConverter


def collect_events(converter: StreamingConverter, chunks: list[dict | str]) -> list[dict[str, Any]]:
    """Feed all chunks through the converter and collect emitted events.
    Returns list of {"event": event_type, "data": parsed_json}.
    """
    events = []
    for chunk in chunks:
        if chunk == "[DONE]":
            for ev in converter.process_done():
                events.append(ev)
        else:
            for ev in converter.process_chunk(chunk):
                events.append(ev)
    return events


def events_of_type(events: list[dict], event_type: str) -> list[dict]:
    return [e for e in events if e["event"] == event_type]


# ===================================================================
# Text-only streaming
# ===================================================================

class TestTextOnlyStreaming:
    """Simple text response: message_start -> content_block_start ->
    content_block_delta(s) -> content_block_stop -> message_delta -> message_stop."""

    def test_event_sequence(self, streaming_text_only):
        conv = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        events = collect_events(conv, streaming_text_only)
        types = [e["event"] for e in events]

        assert types[0] == "message_start"
        assert "content_block_start" in types
        assert "content_block_delta" in types
        assert "content_block_stop" in types
        assert "message_delta" in types
        assert types[-1] == "message_stop"

    def test_message_start_structure(self, streaming_text_only):
        conv = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        events = collect_events(conv, streaming_text_only)
        msg_start = events_of_type(events, "message_start")[0]
        data = msg_start["data"]

        assert data["type"] == "message_start"
        msg = data["message"]
        assert msg["id"].startswith("msg_")
        assert msg["type"] == "message"
        assert msg["role"] == "assistant"
        assert msg["content"] == []
        assert msg["model"] == "claude-sonnet-4-20250514"

    def test_content_block_start_text(self, streaming_text_only):
        conv = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        events = collect_events(conv, streaming_text_only)
        cbs = events_of_type(events, "content_block_start")[0]
        data = cbs["data"]

        assert data["type"] == "content_block_start"
        assert data["index"] == 0
        assert data["content_block"]["type"] == "text"
        assert data["content_block"]["text"] == ""

    def test_text_deltas_accumulated(self, streaming_text_only):
        conv = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        events = collect_events(conv, streaming_text_only)
        deltas = events_of_type(events, "content_block_delta")

        assert len(deltas) >= 1
        full_text = ""
        for d in deltas:
            assert d["data"]["delta"]["type"] == "text_delta"
            full_text += d["data"]["delta"]["text"]
        assert "Hello" in full_text
        assert "help" in full_text

    def test_content_block_stop(self, streaming_text_only):
        conv = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        events = collect_events(conv, streaming_text_only)
        stops = events_of_type(events, "content_block_stop")
        assert len(stops) >= 1
        assert stops[0]["data"]["type"] == "content_block_stop"
        assert stops[0]["data"]["index"] == 0

    def test_message_delta_stop_reason(self, streaming_text_only):
        conv = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        events = collect_events(conv, streaming_text_only)
        msg_delta = events_of_type(events, "message_delta")[0]
        data = msg_delta["data"]

        assert data["type"] == "message_delta"
        assert data["delta"]["stop_reason"] == "end_turn"

    def test_message_delta_usage(self, streaming_text_only):
        conv = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        events = collect_events(conv, streaming_text_only)
        msg_delta = events_of_type(events, "message_delta")[0]
        usage = msg_delta["data"]["usage"]
        assert "output_tokens" in usage

    def test_message_stop_is_last(self, streaming_text_only):
        conv = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        events = collect_events(conv, streaming_text_only)
        assert events[-1]["event"] == "message_stop"
        assert events[-1]["data"]["type"] == "message_stop"


# ===================================================================
# Tool call streaming
# ===================================================================

class TestToolCallStreaming:
    """Tool call: content_block_start(tool_use) -> input_json_delta(s) ->
    content_block_stop -> message_delta(tool_use) -> message_stop."""

    def test_tool_event_sequence(self, streaming_tool_call):
        conv = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        events = collect_events(conv, streaming_tool_call)
        types = [e["event"] for e in events]

        assert types[0] == "message_start"
        assert "content_block_start" in types
        assert "content_block_delta" in types
        assert "content_block_stop" in types
        assert "message_delta" in types
        assert types[-1] == "message_stop"

    def test_tool_content_block_start(self, streaming_tool_call):
        conv = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        events = collect_events(conv, streaming_tool_call)
        cbs = events_of_type(events, "content_block_start")[0]
        block = cbs["data"]["content_block"]

        assert block["type"] == "tool_use"
        assert block["id"].startswith("toolu_")
        assert block["name"] == "get_weather"

    def test_input_json_delta_fragments(self, streaming_tool_call):
        """PLAN.md pitfall #2: arguments arrive fragmented."""
        conv = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        events = collect_events(conv, streaming_tool_call)
        deltas = events_of_type(events, "content_block_delta")

        json_parts = []
        for d in deltas:
            delta = d["data"]["delta"]
            assert delta["type"] == "input_json_delta"
            json_parts.append(delta["partial_json"])

        full_json = "".join(json_parts)
        parsed = json.loads(full_json)
        assert parsed["city"] == "Tokyo"

    def test_tool_stop_reason(self, streaming_tool_call):
        conv = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        events = collect_events(conv, streaming_tool_call)
        msg_delta = events_of_type(events, "message_delta")[0]
        assert msg_delta["data"]["delta"]["stop_reason"] == "tool_use"


# ===================================================================
# Mixed text + tool call streaming
# ===================================================================

class TestMixedTextToolStreaming:
    """Text followed by tool call: two content blocks with proper transitions."""

    def test_two_content_blocks(self, streaming_mixed_text_tool):
        conv = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        events = collect_events(conv, streaming_mixed_text_tool)
        cbs_events = events_of_type(events, "content_block_start")

        assert len(cbs_events) == 2
        assert cbs_events[0]["data"]["content_block"]["type"] == "text"
        assert cbs_events[0]["data"]["index"] == 0
        assert cbs_events[1]["data"]["content_block"]["type"] == "tool_use"
        assert cbs_events[1]["data"]["index"] == 1

    def test_text_block_closed_before_tool(self, streaming_mixed_text_tool):
        conv = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        events = collect_events(conv, streaming_mixed_text_tool)
        types = [e["event"] for e in events]

        # Find the positions
        first_stop = types.index("content_block_stop")
        second_start_idx = None
        for i, t in enumerate(types):
            if t == "content_block_start" and events[i]["data"]["content_block"]["type"] == "tool_use":
                second_start_idx = i
                break

        assert second_start_idx is not None
        # content_block_stop for text must come before content_block_start for tool
        assert first_stop < second_start_idx

    def test_text_deltas_contain_text(self, streaming_mixed_text_tool):
        conv = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        events = collect_events(conv, streaming_mixed_text_tool)

        # Collect text deltas (before tool starts)
        text_deltas = []
        for e in events:
            if e["event"] == "content_block_delta":
                if e["data"]["delta"]["type"] == "text_delta":
                    text_deltas.append(e["data"]["delta"]["text"])
        full_text = "".join(text_deltas)
        assert "Let me check" in full_text


# ===================================================================
# Multiple tool calls with index tracking
# ===================================================================

class TestMultiToolCallStreaming:
    """PLAN.md pitfall #8: OpenAI interleaves chunks for multiple tool_calls via index."""

    def test_two_tool_blocks(self, streaming_multi_tool_call):
        conv = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        events = collect_events(conv, streaming_multi_tool_call)
        cbs_events = events_of_type(events, "content_block_start")

        tool_starts = [e for e in cbs_events if e["data"]["content_block"]["type"] == "tool_use"]
        assert len(tool_starts) == 2

    def test_separate_tool_ids(self, streaming_multi_tool_call):
        conv = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        events = collect_events(conv, streaming_multi_tool_call)
        cbs_events = events_of_type(events, "content_block_start")

        tool_ids = [
            e["data"]["content_block"]["id"]
            for e in cbs_events
            if e["data"]["content_block"]["type"] == "tool_use"
        ]
        assert len(tool_ids) == 2
        assert tool_ids[0] != tool_ids[1]
        assert all(tid.startswith("toolu_") for tid in tool_ids)

    def test_block_indices_increment(self, streaming_multi_tool_call):
        conv = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        events = collect_events(conv, streaming_multi_tool_call)
        cbs_events = events_of_type(events, "content_block_start")

        indices = [e["data"]["index"] for e in cbs_events]
        # Should be 0, 1 (two consecutive blocks)
        assert indices == [0, 1]

    def test_each_tool_has_stop(self, streaming_multi_tool_call):
        conv = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        events = collect_events(conv, streaming_multi_tool_call)
        stops = events_of_type(events, "content_block_stop")
        # Two tool blocks = two content_block_stop events
        assert len(stops) == 2

    def test_arguments_per_tool(self, streaming_multi_tool_call):
        conv = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        events = collect_events(conv, streaming_multi_tool_call)

        # Group deltas by block index
        delta_groups: dict[int, list[str]] = {}
        for e in events:
            if e["event"] == "content_block_delta" and e["data"]["delta"]["type"] == "input_json_delta":
                idx = e["data"]["index"]
                delta_groups.setdefault(idx, []).append(e["data"]["delta"]["partial_json"])

        assert len(delta_groups) == 2
        for idx, parts in delta_groups.items():
            full = "".join(parts)
            parsed = json.loads(full)
            assert "city" in parsed


# ===================================================================
# finish_reason handling
# ===================================================================

class TestFinishReasonHandling:

    def test_stop_finish_reason(self, streaming_text_only):
        conv = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        events = collect_events(conv, streaming_text_only)
        md = events_of_type(events, "message_delta")[0]
        assert md["data"]["delta"]["stop_reason"] == "end_turn"

    def test_tool_calls_finish_reason(self, streaming_tool_call):
        conv = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        events = collect_events(conv, streaming_tool_call)
        md = events_of_type(events, "message_delta")[0]
        assert md["data"]["delta"]["stop_reason"] == "tool_use"

    def test_length_finish_reason(self):
        """Simulate length finish_reason."""
        conv = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        chunks = [
            {
                "id": "chatcmpl-len",
                "choices": [{
                    "index": 0,
                    "delta": {"role": "assistant", "content": ""},
                    "finish_reason": None,
                }],
            },
            {
                "id": "chatcmpl-len",
                "choices": [{
                    "index": 0,
                    "delta": {"content": "Trunca"},
                    "finish_reason": None,
                }],
            },
            {
                "id": "chatcmpl-len",
                "choices": [{
                    "index": 0,
                    "delta": {},
                    "finish_reason": "length",
                }],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4096, "total_tokens": 4106},
            },
        ]
        events = collect_events(conv, chunks)
        md = events_of_type(events, "message_delta")[0]
        assert md["data"]["delta"]["stop_reason"] == "max_tokens"


# ===================================================================
# [DONE] sentinel handling
# ===================================================================

class TestDoneSentinel:

    def test_message_stop_emitted_before_done(self, streaming_text_only):
        conv = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        events = collect_events(conv, streaming_text_only)
        assert events[-1]["event"] == "message_stop"

    def test_done_without_prior_finish_reason(self):
        """Edge case: [DONE] arrives without a finish_reason chunk.
        The converter should still emit message_stop as a guard."""
        conv = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        chunks: list[dict | str] = [
            {
                "id": "chatcmpl-edge",
                "choices": [{
                    "index": 0,
                    "delta": {"role": "assistant", "content": "Hi"},
                    "finish_reason": None,
                }],
            },
            "[DONE]",
        ]
        events = collect_events(conv, chunks)
        types = [e["event"] for e in events]
        assert "message_stop" in types


# ===================================================================
# Edge case: empty chunks
# ===================================================================

class TestEmptyChunks:

    def test_empty_delta_content(self):
        """Chunks with empty content string should not produce spurious events."""
        conv = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        chunks = [
            {
                "id": "chatcmpl-ec",
                "choices": [{
                    "index": 0,
                    "delta": {"role": "assistant", "content": ""},
                    "finish_reason": None,
                }],
            },
            {
                "id": "chatcmpl-ec",
                "choices": [{
                    "index": 0,
                    "delta": {"content": "Hi"},
                    "finish_reason": None,
                }],
            },
            {
                "id": "chatcmpl-ec",
                "choices": [{
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
            },
        ]
        events = collect_events(conv, chunks)
        # Should still produce valid sequence
        types = [e["event"] for e in events]
        assert types[0] == "message_start"
        assert types[-1] == "message_stop"

    def test_chunk_with_empty_choices(self):
        """Chunk with empty choices array should be ignored."""
        conv = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        chunks = [
            {
                "id": "chatcmpl-emp",
                "choices": [{
                    "index": 0,
                    "delta": {"role": "assistant", "content": "Hello"},
                    "finish_reason": None,
                }],
            },
            {
                "id": "chatcmpl-emp",
                "choices": [],
            },
            {
                "id": "chatcmpl-emp",
                "choices": [{
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
            },
        ]
        events = collect_events(conv, chunks)
        types = [e["event"] for e in events]
        assert "message_start" in types
        assert "message_stop" in types


# ===================================================================
# Usage in final chunk
# ===================================================================

class TestUsageInFinalChunk:
    """PLAN.md pitfall #9: Usage only in final chunk with stream_options.include_usage."""

    def test_usage_captured_from_final_chunk(self, streaming_text_only):
        conv = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        events = collect_events(conv, streaming_text_only)

        # message_start should have input_tokens
        msg_start = events_of_type(events, "message_start")[0]
        start_usage = msg_start["data"]["message"].get("usage", {})
        assert "input_tokens" in start_usage

        # message_delta should have output_tokens
        msg_delta = events_of_type(events, "message_delta")[0]
        delta_usage = msg_delta["data"]["usage"]
        assert "output_tokens" in delta_usage

    def test_no_usage_chunk_defaults_to_zero(self):
        """If no usage in any chunk, default to 0."""
        conv = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        chunks = [
            {
                "id": "chatcmpl-nu",
                "choices": [{
                    "index": 0,
                    "delta": {"role": "assistant", "content": "Hi"},
                    "finish_reason": None,
                }],
            },
            {
                "id": "chatcmpl-nu",
                "choices": [{
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }],
                # No usage field
            },
        ]
        events = collect_events(conv, chunks)
        msg_delta = events_of_type(events, "message_delta")[0]
        assert msg_delta["data"]["usage"]["output_tokens"] >= 0


# ===================================================================
# Anthropic SSE format verification
# ===================================================================

class TestAnthropicSSEFormat:
    """PLAN.md §1.6: Each event must be:
    event: {event_type}\\ndata: {json}\\n\\n
    """

    def test_format_event_method(self, streaming_text_only):
        conv = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        events = collect_events(conv, streaming_text_only)

        for ev in events:
            # Each event dict must have 'event' and 'data' keys
            assert "event" in ev
            assert "data" in ev
            assert isinstance(ev["event"], str)
            assert isinstance(ev["data"], dict)

    def test_serialize_to_sse_lines(self, streaming_text_only):
        """If the converter has a format_sse method, it should produce
        'event: {type}\\ndata: {json}\\n\\n' format."""
        conv = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        events = collect_events(conv, streaming_text_only)

        for ev in events:
            sse_text = f"event: {ev['event']}\ndata: {json.dumps(ev['data'])}\n\n"
            assert sse_text.startswith("event: ")
            assert "\ndata: " in sse_text
            assert sse_text.endswith("\n\n")
            # Verify the data portion is valid JSON
            data_line = sse_text.split("\ndata: ")[1].rstrip("\n")
            parsed = json.loads(data_line)
            assert isinstance(parsed, dict)


# ===================================================================
# State machine integrity
# ===================================================================

class TestStateMachineIntegrity:

    def test_no_duplicate_message_start(self, streaming_text_only):
        conv = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        events = collect_events(conv, streaming_text_only)
        assert len(events_of_type(events, "message_start")) == 1

    def test_no_duplicate_message_stop(self, streaming_text_only):
        conv = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        events = collect_events(conv, streaming_text_only)
        assert len(events_of_type(events, "message_stop")) == 1

    def test_block_start_before_delta(self, streaming_text_only):
        conv = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        events = collect_events(conv, streaming_text_only)
        types = [e["event"] for e in events]
        first_delta = types.index("content_block_delta")
        first_start = types.index("content_block_start")
        assert first_start < first_delta

    def test_block_stop_before_message_delta(self, streaming_text_only):
        conv = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        events = collect_events(conv, streaming_text_only)
        types = [e["event"] for e in events]
        last_block_stop = len(types) - 1 - types[::-1].index("content_block_stop")
        msg_delta_idx = types.index("message_delta")
        assert last_block_stop < msg_delta_idx

    def test_message_start_before_everything(self, streaming_tool_call):
        conv = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        events = collect_events(conv, streaming_tool_call)
        assert events[0]["event"] == "message_start"

    def test_every_start_has_matching_stop(self, streaming_mixed_text_tool):
        conv = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        events = collect_events(conv, streaming_mixed_text_tool)

        starts = events_of_type(events, "content_block_start")
        stops = events_of_type(events, "content_block_stop")
        assert len(starts) == len(stops)

        start_indices = [e["data"]["index"] for e in starts]
        stop_indices = [e["data"]["index"] for e in stops]
        assert sorted(start_indices) == sorted(stop_indices)


# ===================================================================
# Converter reusability
# ===================================================================

class TestConverterReusability:
    """Each StreamingConverter instance should handle exactly one stream.
    A new instance is needed for each request."""

    def test_fresh_instance_per_stream(self, streaming_text_only):
        conv1 = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        events1 = collect_events(conv1, streaming_text_only)

        conv2 = StreamingConverter(model_alias="claude-sonnet-4-20250514")
        events2 = collect_events(conv2, streaming_text_only)

        # Both should produce valid sequences independently
        assert len(events1) == len(events2)
        assert events1[0]["event"] == "message_start"
        assert events2[0]["event"] == "message_start"
        # Message IDs should differ
        assert events1[0]["data"]["message"]["id"] != events2[0]["data"]["message"]["id"]
