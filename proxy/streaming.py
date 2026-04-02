import json
import uuid
from typing import Any, AsyncIterator


def _gen_msg_id() -> str:
    return f"msg_{uuid.uuid4().hex[:24]}"


def _gen_tool_id() -> str:
    return f"toolu_{uuid.uuid4().hex[:24]}"


def _sse_event(event_type: str, data: dict[str, Any]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def _map_finish_reason(reason: str | None, stop_sequences: list[str] | None = None) -> str:
    if reason == "tool_calls":
        return "tool_use"
    if reason == "length":
        return "max_tokens"
    if reason == "stop":
        return "stop_sequence" if stop_sequences else "end_turn"
    return "end_turn"


class StreamState:
    __slots__ = (
        "block_index", "active_block", "message_started", "tool_states",
        "msg_id", "anthropic_model", "stop_sequences", "input_tokens",
        "output_tokens", "_current_tool_block_index",
    )

    def __init__(self, anthropic_model: str, stop_sequences: list[str] | None = None):
        self.block_index: int = 0
        self.active_block: str | None = None
        self.message_started: bool = False
        self.tool_states: dict[int, dict[str, Any]] = {}
        self.msg_id = _gen_msg_id()
        self.anthropic_model = anthropic_model
        self.stop_sequences = stop_sequences
        self.input_tokens: int = 0
        self.output_tokens: int = 0
        self._current_tool_block_index: dict[int, int] = {}


def _emit_message_start(state: StreamState) -> str:
    state.message_started = True
    return _sse_event("message_start", {
        "type": "message_start",
        "message": {
            "id": state.msg_id,
            "type": "message",
            "role": "assistant",
            "content": [],
            "model": state.anthropic_model,
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {
                "input_tokens": state.input_tokens,
                "output_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
        },
    })


def _emit_content_block_start_text(state: StreamState) -> str:
    return _sse_event("content_block_start", {
        "type": "content_block_start",
        "index": state.block_index,
        "content_block": {"type": "text", "text": ""},
    })


def _emit_content_block_start_tool(state: StreamState, tool_id: str, name: str) -> str:
    return _sse_event("content_block_start", {
        "type": "content_block_start",
        "index": state.block_index,
        "content_block": {
            "type": "tool_use",
            "id": tool_id,
            "name": name,
            "input": {},
        },
    })


def _emit_content_block_stop(state: StreamState, index: int) -> str:
    return _sse_event("content_block_stop", {
        "type": "content_block_stop",
        "index": index,
    })


def _emit_text_delta(state: StreamState, text: str) -> str:
    return _sse_event("content_block_delta", {
        "type": "content_block_delta",
        "index": state.block_index,
        "delta": {"type": "text_delta", "text": text},
    })


def _emit_input_json_delta(state: StreamState, block_idx: int, partial: str) -> str:
    return _sse_event("content_block_delta", {
        "type": "content_block_delta",
        "index": block_idx,
        "delta": {"type": "input_json_delta", "partial_json": partial},
    })


def _emit_message_delta(state: StreamState, stop_reason: str) -> str:
    return _sse_event("message_delta", {
        "type": "message_delta",
        "delta": {
            "stop_reason": stop_reason,
            "stop_sequence": None,
        },
        "usage": {"output_tokens": state.output_tokens},
    })


def _emit_message_stop() -> str:
    return _sse_event("message_stop", {"type": "message_stop"})


def process_chunk(state: StreamState, chunk: dict[str, Any]) -> list[str]:
    events: list[str] = []

    if not state.message_started:
        usage = chunk.get("usage")
        if usage:
            state.input_tokens = usage.get("prompt_tokens", 0)
        events.append(_emit_message_start(state))

    choices = chunk.get("choices", [])
    if not choices:
        usage = chunk.get("usage")
        if usage:
            state.output_tokens = usage.get("completion_tokens", state.output_tokens)
        return events

    choice = choices[0]
    delta = choice.get("delta", {})
    finish_reason = choice.get("finish_reason")

    text_content = delta.get("content")
    if text_content:
        if state.active_block != "text":
            if state.active_block is not None:
                events.append(_emit_content_block_stop(state, state.block_index))
                state.block_index += 1
            events.append(_emit_content_block_start_text(state))
            state.active_block = "text"
        events.append(_emit_text_delta(state, text_content))

    tool_calls = delta.get("tool_calls")
    if tool_calls:
        for tc in tool_calls:
            tc_index = tc.get("index", 0)

            if tc.get("id"):
                if state.active_block is not None:
                    events.append(_emit_content_block_stop(state, state.block_index))
                    state.block_index += 1

                tool_id = _gen_tool_id()
                fn = tc.get("function", {})
                name = fn.get("name", "")
                state.tool_states[tc_index] = {
                    "id": tool_id,
                    "name": name,
                    "args": "",
                }
                state._current_tool_block_index[tc_index] = state.block_index
                events.append(_emit_content_block_start_tool(state, tool_id, name))
                state.active_block = "tool_use"

            fn = tc.get("function", {})
            args_frag = fn.get("arguments", "")
            if args_frag and tc_index in state.tool_states:
                state.tool_states[tc_index]["args"] += args_frag
                block_idx = state._current_tool_block_index.get(tc_index, state.block_index)
                events.append(_emit_input_json_delta(state, block_idx, args_frag))

    if finish_reason is not None:
        usage = chunk.get("usage")
        if usage:
            state.output_tokens = usage.get("completion_tokens", state.output_tokens)

        if state.active_block is not None:
            events.append(_emit_content_block_stop(state, state.block_index))
            state.active_block = None

        stop_reason = _map_finish_reason(finish_reason, state.stop_sequences)
        events.append(_emit_message_delta(state, stop_reason))
        events.append(_emit_message_stop())

    return events


async def transform_sse_stream(
    openai_stream: AsyncIterator[bytes],
    anthropic_model: str,
    stop_sequences: list[str] | None = None,
) -> AsyncIterator[str]:
    state = StreamState(anthropic_model, stop_sequences)
    message_stopped = False

    async for raw_line in openai_stream:
        line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
        line = line.strip()

        if not line:
            continue

        if line == "data: [DONE]":
            if not message_stopped:
                if not state.message_started:
                    yield _emit_message_start(state)
                if state.active_block is not None:
                    yield _emit_content_block_stop(state, state.block_index)
                yield _emit_message_delta(state, "end_turn")
                yield _emit_message_stop()
            return

        if not line.startswith("data: "):
            continue

        json_str = line[6:]
        try:
            chunk = json.loads(json_str)
        except json.JSONDecodeError:
            continue

        events = process_chunk(state, chunk)
        for ev in events:
            if "message_stop" in ev:
                message_stopped = True
            yield ev

    if not message_stopped:
        if not state.message_started:
            yield _emit_message_start(state)
        if state.active_block is not None:
            yield _emit_content_block_stop(state, state.block_index)
        yield _emit_message_delta(state, "end_turn")
        yield _emit_message_stop()


class StreamingConverter:
    """Class wrapper for test compatibility. Wraps StreamState + process_chunk."""

    def __init__(self, model_alias: str, stop_sequences: list[str] | None = None):
        self._state = StreamState(model_alias, stop_sequences)
        self._message_stopped = False

    def _parse_sse(self, raw: str) -> dict[str, Any]:
        lines = raw.strip().split("\n")
        event_type = ""
        data_str = ""
        for line in lines:
            if line.startswith("event: "):
                event_type = line[7:]
            elif line.startswith("data: "):
                data_str = line[6:]
        return {"event": event_type, "data": json.loads(data_str)}

    def process_chunk(self, chunk: dict[str, Any]) -> list[dict[str, Any]]:
        raw_events = process_chunk(self._state, chunk)
        parsed = [self._parse_sse(ev) for ev in raw_events]
        for ev in parsed:
            if ev["event"] == "message_stop":
                self._message_stopped = True
        return parsed

    def process_done(self) -> list[dict[str, Any]]:
        if self._message_stopped:
            return []
        events: list[dict[str, Any]] = []
        if not self._state.message_started:
            events.append(self._parse_sse(_emit_message_start(self._state)))
        if self._state.active_block is not None:
            events.append(self._parse_sse(_emit_content_block_stop(self._state, self._state.block_index)))
        events.append(self._parse_sse(_emit_message_delta(self._state, "end_turn")))
        events.append(self._parse_sse(_emit_message_stop()))
        self._message_stopped = True
        return events
