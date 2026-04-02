from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FunctionCall(BaseModel):
    name: str = ""
    arguments: str = ""


class ToolCall(BaseModel):
    id: str = ""
    type: str = "function"
    function: FunctionCall = Field(default_factory=FunctionCall)
    index: int = 0


class ChatMessage(BaseModel):
    role: str
    content: Any = None  # str | list[dict] | None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[dict[str, Any]]
    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    stop: list[str] | None = None
    stream: bool = False
    stream_options: dict[str, Any] | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: Any = None
    parallel_tool_calls: bool | None = None

    model_config = {"extra": "allow"}


class ChoiceDelta(BaseModel):
    role: str | None = None
    content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


class Choice(BaseModel):
    index: int = 0
    message: dict[str, Any] | None = None
    delta: ChoiceDelta | None = None
    finish_reason: str | None = None


class CompletionUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    id: str = ""
    object: str = "chat.completion"
    model: str = ""
    choices: list[Choice] = Field(default_factory=list)
    usage: CompletionUsage | None = None
