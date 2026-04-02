# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

openClaude is an API proxy that enables Claude Code to work with any OpenAI-compatible LLM (Kimi 2.5, GLM5, Qwen3, vLLM, etc.). It intercepts Anthropic Messages API requests from Claude Code, converts them to OpenAI Chat Completions API format, forwards to the target LLM, and converts responses back. Claude Code connects via `ANTHROPIC_BASE_URL` env var.

## Architecture

```
Claude Code (unmodified) → ANTHROPIC_BASE_URL → openClaude Proxy → Any OpenAI-compatible LLM
```

Three core conversion layers:
1. **Request** (`converter/request.py`): Anthropic messages → OpenAI chat completions (system prompts, content blocks, tool definitions)
2. **Response** (`converter/response.py`): OpenAI completion → Anthropic message (stop_reason, usage, tool_calls → tool_use blocks)
3. **Streaming** (`streaming.py`): OpenAI flat SSE → Anthropic hierarchical SSE (state machine converting flat chunks to message_start/content_block_start/delta/stop lifecycle)

Critical conversion details: `tool_choice "any"→"required"`, `input_schema→parameters` wrapping, `tool_result` role splitting, image block data URI construction, `msg_`/`toolu_` ID generation. See PLAN.md §1.2–§1.7.

## Tech Stack

- **Framework**: FastAPI + uvicorn
- **HTTP Client**: httpx (AsyncClient, streaming support)
- **Config**: YAML + env vars (`config.example.yaml`)
- **Token counting**: tiktoken
- **Testing**: pytest + httpx + pytest-asyncio

## Project Structure

```
proxy/
├── server.py              # FastAPI app, route handlers
├── config.py              # YAML + env var config loading
├── auth.py                # Header translation (x-api-key → Bearer)
├── models.py              # Model name mapping + capability lookup
├── streaming.py           # SSE state machine (PLAN.md §1.6)
├── schemas/
│   ├── anthropic.py       # Pydantic models for Anthropic types
│   └── openai.py          # Pydantic models for OpenAI types
└── converter/
    ├── request.py         # Anthropic request → OpenAI request
    ├── response.py        # OpenAI response → Anthropic response
    ├── tools.py           # Tool definitions, tool_choice, tool_result
    ├── content.py         # Content blocks (text, image, document)
    └── errors.py          # Error format conversion
tests/
├── test_request_converter.py
├── test_response_converter.py
├── test_tool_converter.py
├── test_streaming.py
├── test_error_converter.py
├── test_integration.py    # End-to-end with mock backend
└── fixtures/              # Recorded request/response pairs
```

## Build & Run Commands

```bash
pip install -r requirements.txt

# Run proxy
uvicorn proxy.server:app --reload --port 8082
# or: python -m proxy.server

# Use with Claude Code
ANTHROPIC_BASE_URL=http://localhost:8082 claude

# Tests
pytest
pytest tests/test_streaming.py -v          # single file
pytest tests/test_streaming.py::test_fn -v # single test

# Docker
docker compose up --build
```

## Key Design Decisions

- Streaming state machine (`streaming.py`) is the highest-complexity module — see PLAN.md §1.6 for pseudocode
- `converter/tools.py` handles the most pitfall-prone conversions — see PLAN.md "Known Pitfalls" section
- Proxy generates Anthropic-format IDs (`msg_`, `toolu_` prefixes), never passes through OpenAI IDs
- Error responses must be in Anthropic format (`converter/errors.py`), otherwise Claude Code crashes
