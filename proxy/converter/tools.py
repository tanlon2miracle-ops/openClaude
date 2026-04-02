from typing import Any


def convert_tool_definitions(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for tool in tools:
        result.append({
            "type": "function",
            "function": {
                "name": tool.get("name", ""),
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {}),
            },
        })
    return result


def convert_tool_choice(choice: Any) -> Any:
    if choice is None:
        return None
    if isinstance(choice, str):
        return choice
    if isinstance(choice, dict):
        ctype = choice.get("type")
        if ctype == "auto":
            return "auto"
        if ctype == "any":
            return "required"
        if ctype == "none":
            return "none"
        if ctype == "tool":
            return {"type": "function", "function": {"name": choice.get("name", "")}}
    return None


def should_disable_parallel_tools(choice: Any) -> bool | None:
    if isinstance(choice, dict) and choice.get("disable_parallel_tool_use"):
        return False  # parallel_tool_calls = false (inverted)
    return None


def split_tool_result_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for msg in messages:
        if msg.get("role") != "user":
            result.append(msg)
            continue

        content = msg.get("content")
        if not isinstance(content, list):
            result.append(msg)
            continue

        text_parts = []
        for block in content:
            if isinstance(block, str):
                text_parts.append(block)
                continue
            if block.get("type") == "tool_result":
                if text_parts:
                    result.append({"role": "user", "content": _flatten_text_parts(text_parts)})
                    text_parts = []
                tool_content = _extract_tool_result_content(block)
                tool_call_id = block.get("tool_use_id", "")
                if not tool_call_id.startswith("call_"):
                    tool_call_id = f"call_{tool_call_id.replace('toolu_', '')}" if tool_call_id else tool_call_id
                result.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": tool_content,
                })
            else:
                text_parts.append(block)

        if text_parts:
            result.append({"role": "user", "content": _flatten_text_parts(text_parts)})

    return result


def _extract_tool_result_content(block: dict[str, Any]) -> str:
    content = block.get("content")
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, str):
                texts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                texts.append(item.get("text", ""))
        return "\n".join(texts)
    return str(content)


def _flatten_text_parts(parts: list) -> Any:
    text_only = []
    mixed = []
    for p in parts:
        if isinstance(p, str):
            text_only.append(p)
            mixed.append({"type": "text", "text": p})
        elif isinstance(p, dict):
            mixed.append(p)
        else:
            mixed.append(p)

    if len(mixed) == len(text_only):
        return " ".join(text_only)
    return mixed


# Aliases for test compatibility
convert_tools = convert_tool_definitions
convert_tool_result_messages = split_tool_result_messages
