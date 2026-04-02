from typing import Any

from proxy.converter.content import convert_message_content_to_openai
from proxy.converter.tools import (
    convert_tool_choice,
    convert_tool_definitions,
    should_disable_parallel_tools,
    split_tool_result_messages,
)


def convert_system_prompt(system: Any) -> str:
    if system is None:
        return ""
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        parts = []
        for block in system:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n\n".join(parts)
    return str(system)


def convert_assistant_message(msg: dict[str, Any]) -> dict[str, Any]:
    content = msg.get("content")
    if isinstance(content, list):
        text_parts = []
        tool_calls = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
                elif block.get("type") == "tool_use":
                    tc_id = block.get("id", "")
                    if not tc_id.startswith("call_"):
                        tc_id = f"call_{tc_id.replace('toolu_', '')}" if tc_id else tc_id
                    import json
                    tool_calls.append({
                        "id": tc_id,
                        "type": "function",
                        "function": {
                            "name": block.get("name", ""),
                            "arguments": json.dumps(block.get("input", {})),
                        },
                    })

        result: dict[str, Any] = {"role": "assistant"}
        result["content"] = "\n".join(text_parts) if text_parts else None
        if tool_calls:
            result["tool_calls"] = tool_calls
        return result
    return {"role": "assistant", "content": convert_message_content_to_openai(content)}


def convert_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    processed = split_tool_result_messages(messages)
    result = []
    for msg in processed:
        role = msg.get("role")
        if role == "assistant":
            result.append(convert_assistant_message(msg))
        elif role == "tool":
            result.append(msg)
        else:
            result.append({
                "role": role or "user",
                "content": convert_message_content_to_openai(msg.get("content")),
            })
    return result


def convert_request(request_body: dict[str, Any], target_model: str | dict[str, str]) -> dict[str, Any]:
    if isinstance(target_model, dict):
        model_map = target_model
        src_model = request_body.get("model", "")
        resolved = model_map.get(src_model, src_model)
    else:
        resolved = target_model

    openai_req: dict[str, Any] = {
        "model": resolved,
        "messages": [],
    }

    system_text = convert_system_prompt(request_body.get("system"))
    if system_text:
        openai_req["messages"].append({"role": "system", "content": system_text})

    openai_req["messages"].extend(convert_messages(request_body.get("messages", [])))

    if "max_tokens" in request_body:
        openai_req["max_tokens"] = request_body["max_tokens"]
    if request_body.get("temperature") is not None:
        openai_req["temperature"] = request_body["temperature"]
    if request_body.get("top_p") is not None:
        openai_req["top_p"] = request_body["top_p"]
    if request_body.get("stop_sequences"):
        openai_req["stop"] = request_body["stop_sequences"]

    openai_req["stream"] = request_body.get("stream", False)
    if openai_req["stream"]:
        openai_req["stream_options"] = {"include_usage": True}

    tools = request_body.get("tools")
    if tools:
        openai_req["tools"] = convert_tool_definitions(tools)

    tool_choice = request_body.get("tool_choice")
    if tool_choice is not None:
        converted_choice = convert_tool_choice(tool_choice)
        if converted_choice is not None:
            openai_req["tool_choice"] = converted_choice
        parallel = should_disable_parallel_tools(tool_choice)
        if parallel is not None:
            openai_req["parallel_tool_calls"] = parallel

    return openai_req
