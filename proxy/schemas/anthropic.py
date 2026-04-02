from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ContentBlockText(BaseModel):
    type: str = "text"
    text: str


class ContentBlockImage(BaseModel):
    type: str = "image"
    source: dict[str, Any]


class ContentBlockToolUse(BaseModel):
    type: str = "tool_use"
    id: str
    name: str
    input: dict[str, Any] = Field(default_factory=dict)


class ContentBlockToolResult(BaseModel):
    type: str = "tool_result"
    tool_use_id: str
    content: Any = None
    is_error: bool = False


class ToolDefinition(BaseModel):
    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)


class MessagesRequest(BaseModel):
    model: str
    messages: list[dict[str, Any]]
    max_tokens: int = 4096
    system: Any = None  # str | list[dict]
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    stop_sequences: list[str] | None = None
    stream: bool = False
    tools: list[dict[str, Any]] | None = None
    tool_choice: Any = None  # dict | None
    thinking: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None

    model_config = {"extra": "allow"}


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


class MessagesResponse(BaseModel):
    id: str
    type: str = "message"
    role: str = "assistant"
    content: list[dict[str, Any]] = Field(default_factory=list)
    model: str = ""
    stop_reason: str | None = None
    stop_sequence: str | None = None
    usage: Usage = Field(default_factory=Usage)


class AnthropicError(BaseModel):
    type: str = "error"
    error: dict[str, str]
