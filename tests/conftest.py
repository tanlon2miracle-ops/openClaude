"""Shared pytest fixtures for openClaude test suite."""

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Fixture file loaders
# ---------------------------------------------------------------------------

def _load_json(relative_path: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / relative_path).read_text())


def _load_text(relative_path: str) -> str:
    return (FIXTURES_DIR / relative_path).read_text()


# ---------------------------------------------------------------------------
# Anthropic request payloads
# ---------------------------------------------------------------------------

@pytest.fixture
def anthropic_basic_text() -> dict[str, Any]:
    return _load_json("anthropic_requests/basic_text.json")


@pytest.fixture
def anthropic_system_array() -> dict[str, Any]:
    return _load_json("anthropic_requests/system_array.json")


@pytest.fixture
def anthropic_full_params() -> dict[str, Any]:
    return _load_json("anthropic_requests/full_params.json")


@pytest.fixture
def anthropic_image_base64() -> dict[str, Any]:
    return _load_json("anthropic_requests/image_base64.json")


@pytest.fixture
def anthropic_image_url() -> dict[str, Any]:
    return _load_json("anthropic_requests/image_url.json")


@pytest.fixture
def anthropic_tool_use() -> dict[str, Any]:
    return _load_json("anthropic_requests/tool_use.json")


@pytest.fixture
def anthropic_tool_result() -> dict[str, Any]:
    return _load_json("anthropic_requests/tool_result.json")


@pytest.fixture
def anthropic_mixed_tool_result_text() -> dict[str, Any]:
    return _load_json("anthropic_requests/mixed_tool_result_text.json")


# ---------------------------------------------------------------------------
# OpenAI response payloads
# ---------------------------------------------------------------------------

@pytest.fixture
def openai_basic_text() -> dict[str, Any]:
    return _load_json("openai_responses/basic_text.json")


@pytest.fixture
def openai_tool_call() -> dict[str, Any]:
    return _load_json("openai_responses/tool_call.json")


@pytest.fixture
def openai_multi_tool_call() -> dict[str, Any]:
    return _load_json("openai_responses/multi_tool_call.json")


@pytest.fixture
def openai_length_stop() -> dict[str, Any]:
    return _load_json("openai_responses/length_stop.json")


# ---------------------------------------------------------------------------
# Streaming SSE sequences (raw text → parsed chunk list)
# ---------------------------------------------------------------------------

def parse_sse_lines(raw: str) -> list[dict[str, Any] | str]:
    """Parse OpenAI SSE text into a list of JSON dicts (or the literal '[DONE]')."""
    chunks: list[dict[str, Any] | str] = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line or not line.startswith("data: "):
            continue
        payload = line[len("data: "):]
        if payload == "[DONE]":
            chunks.append("[DONE]")
        else:
            chunks.append(json.loads(payload))
    return chunks


@pytest.fixture
def streaming_text_only() -> list[dict[str, Any] | str]:
    return parse_sse_lines(_load_text("streaming/text_only.txt"))


@pytest.fixture
def streaming_tool_call() -> list[dict[str, Any] | str]:
    return parse_sse_lines(_load_text("streaming/tool_call.txt"))


@pytest.fixture
def streaming_mixed_text_tool() -> list[dict[str, Any] | str]:
    return parse_sse_lines(_load_text("streaming/mixed_text_tool.txt"))


@pytest.fixture
def streaming_multi_tool_call() -> list[dict[str, Any] | str]:
    return parse_sse_lines(_load_text("streaming/multi_tool_call.txt"))


# ---------------------------------------------------------------------------
# Model mapping (mimics config)
# ---------------------------------------------------------------------------

@pytest.fixture
def model_map() -> dict[str, str]:
    return {
        "claude-sonnet-4-20250514": "kimi-2.5",
        "claude-haiku-4-5-20251001": "kimi-2.5-mini",
        "claude-opus-4-6": "qwen3-235b-a22b",
    }
