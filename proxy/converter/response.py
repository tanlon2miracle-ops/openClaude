import json
import uuid
from typing import Any

from proxy.converter.content import convert_tool_use_to_content_block


def _gen_msg_id() -> str:
    return f"msg_{uuid.uuid4().hex[:24]}"


def _map_stop_reason(finish_reason: str | None, stop_sequences: list[str] | None = None) -> str:
    if finish_reason == "tool_calls":
        return "tool_use"
    if finish_reason == "length":
        return "max_tokens"
    if finish_reason == "stop":
        if stop_sequences:
            return "stop_sequence"
        return "end_turn"
    return "end_turn"


def convert_response(
    openai_resp: dict[str, Any],
    anthropic_model: str,
    stop_sequences: list[str] | None = None,
) -> dict[str, Any]:
    choices = openai_resp.get("choices", [])
    choice = choices[0] if choices else {}
    message = choice.get("message", {})

    content_blocks: list[dict[str, Any]] = []

    text = message.get("content")
    if text:
        content_blocks.append({"type": "text", "text": text})

    tool_calls = message.get("tool_calls")
    if tool_calls:
        for tc in tool_calls:
            content_blocks.append(convert_tool_use_to_content_block(tc))

    finish_reason = choice.get("finish_reason")
    stop_reason = _map_stop_reason(finish_reason, stop_sequences)

    usage = openai_resp.get("usage", {})

    return {
        "id": _gen_msg_id(),
        "type": "message",
        "role": "assistant",
        "content": content_blocks,
        "model": anthropic_model,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
    }
