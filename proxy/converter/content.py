from typing import Any
import json


def convert_content_block_to_openai(block: dict[str, Any]) -> dict[str, Any] | None:
    btype = block.get("type")

    if btype == "text":
        return {"type": "text", "text": block["text"]}

    if btype == "image":
        source = block.get("source", {})
        if source.get("type") == "base64":
            media_type = source.get("media_type", "image/png")
            data = source.get("data", "")
            url = f"data:{media_type};base64,{data}"
        elif source.get("type") == "url":
            url = source.get("url", "")
        else:
            return None
        return {"type": "image_url", "image_url": {"url": url}}

    if btype == "tool_use":
        return None  # handled at message level in response conversion

    if btype == "tool_result":
        return None  # handled by tool converter

    if btype == "document":
        return {"type": "text", "text": "[Unsupported document block]"}

    return None


def convert_message_content_to_openai(content: Any) -> Any:
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append({"type": "text", "text": block})
                continue
            converted = convert_content_block_to_openai(block)
            if converted:
                parts.append(converted)
        if len(parts) == 1 and parts[0].get("type") == "text":
            return parts[0]["text"]
        return parts if parts else ""

    return str(content) if content else ""


def convert_tool_use_to_content_block(tool_call: dict[str, Any]) -> dict[str, Any]:
    func = tool_call.get("function", {})
    args_str = func.get("arguments", "{}")
    try:
        input_obj = json.loads(args_str)
    except (json.JSONDecodeError, TypeError):
        input_obj = {}

    tc_id = tool_call.get("id", "")
    if not tc_id.startswith("toolu_"):
        tc_id = f"toolu_{tc_id.replace('call_', '')}" if tc_id else _gen_tool_id()

    return {
        "type": "tool_use",
        "id": tc_id,
        "name": func.get("name", ""),
        "input": input_obj,
    }


def _gen_tool_id() -> str:
    import uuid
    return f"toolu_{uuid.uuid4().hex[:24]}"
