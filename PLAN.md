# openClaude — Implementation Plan

## Background

Claude Code (npm: @anthropic-ai/claude-code) is a 12MB minified JS single file (cli.js),
hardcoded to use the Anthropic Messages API via `@anthropic-ai/sdk` (which uses Node.js native `fetch`).

**Goal**: Without modifying Claude Code, use an external proxy (`ANTHROPIC_BASE_URL`) for protocol conversion,
enabling any OpenAI-compatible model (Kimi 2.5, GLM5, Qwen3, vLLM, etc.) to drive Claude Code.

**Reference projects**: [a4f-proxy](https://github.com/edxeth/a4f-proxy) (TS/CF Worker), [token_proxy](https://github.com/mxyhi/token_proxy) (Rust), [one-api](https://github.com/songquanpeng/one-api) (Node.js/31K★)

---

## Phase 1: API Proxy Core — P0

### 1.1 Endpoints

- [ ] `POST /v1/messages` — Anthropic Messages API (streaming + non-streaming)
- [ ] `POST /v1/messages/count_tokens` — token counting (tiktoken approximation)
- [ ] `GET /v1/models` — return configured model mapping list
- [ ] `GET /health` — health check
- [ ] Path normalization: handle `/v1/v1/messages`, `//v1/messages`, trailing slashes

### 1.2 Request Conversion (Anthropic → OpenAI)

**Parameter mapping**:

| Anthropic | OpenAI | Notes |
|---|---|---|
| `model` | `model` | Via name mapping table |
| `messages` | `messages` | Content format + role conversion (see §1.4) |
| `system` (string or content block array) | First message `role: "system"` | Flatten array, strip `cache_control` |
| `max_tokens` | `max_tokens` | Direct |
| `temperature` | `temperature` | Direct |
| `top_p` | `top_p` | Direct |
| `top_k` | — | Strip (most backends unsupported) |
| `stop_sequences` | `stop` | Rename |
| `stream` | `stream` | Direct; add `stream_options: {include_usage: true}` |
| `tools` | `tools` | Schema restructuring (see §1.3) |
| `tool_choice` | `tool_choice` | Value mapping (see §1.3) |
| `thinking` | — | Strip or map to provider-specific param |
| `metadata` | — | Strip |
| `cache_control` | — | Strip |

**Headers**:
- Inbound: accept `x-api-key` + `anthropic-version` (Claude Code always sends both)
- Outbound: translate to `Authorization: Bearer <configured_api_key>`

### 1.3 Tool Conversion

**Tool definition**:
```
Anthropic: {"name": "X", "description": "...", "input_schema": {…}}
OpenAI:    {"type": "function", "function": {"name": "X", "description": "...", "parameters": {…}}}
```

**tool_choice mapping** (critical — `any` ≠ OpenAI `any`):

| Anthropic | OpenAI |
|---|---|
| `{"type": "auto"}` | `"auto"` |
| `{"type": "any"}` | `"required"` |
| `{"type": "none"}` | `"none"` |
| `{"type": "tool", "name": "X"}` | `{"type": "function", "function": {"name": "X"}}` |
| `disable_parallel_tool_use: true` | `parallel_tool_calls: false` (invert) |

**tool_result conversion** (role-level structural change):
```
Anthropic (embedded in user message):
  {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_...", "content": "..."}]}

OpenAI (separate message):
  {"role": "tool", "tool_call_id": "call_...", "content": "..."}
```
- Must split user messages containing `tool_result` blocks into separate `role: "tool"` messages
- Preserve ordering: text blocks stay as `role: "user"`, tool_result blocks become `role: "tool"`

### 1.4 Content Block Conversion

| Anthropic Block | OpenAI Equivalent | Direction |
|---|---|---|
| `{"type": "text", "text": "..."}` | `{"type": "text", "text": "..."}` or plain string | Both |
| `{"type": "image", "source": {"type": "base64", "data": "...", "media_type": "image/png"}}` | `{"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}` | Request |
| `{"type": "image", "source": {"type": "url", "url": "..."}}` | `{"type": "image_url", "image_url": {"url": "..."}}` | Request |
| `{"type": "tool_use", "id": "toolu_...", "name": "X", "input": {...}}` | `tool_calls[i]: {"id": "call_...", "type": "function", "function": {"name": "X", "arguments": "{...}"}}` | Response |
| `{"type": "tool_result", ...}` | `{"role": "tool", ...}` | Request (see §1.3) |
| `{"type": "document", ...}` | — | Phase 3: return error or extract text |

### 1.5 Response Conversion (OpenAI → Anthropic)

- Generate Anthropic-format IDs: `msg_` prefix for message, `toolu_` prefix for tool_use
- Convert `tool_calls` array → `content` array of `tool_use` blocks (parse `arguments` JSON string → `input` object)
- Text content → `{"type": "text", "text": "..."}`

**stop_reason mapping**:

| OpenAI `finish_reason` | Anthropic `stop_reason` |
|---|---|
| `stop` | `end_turn` (or `stop_sequence` if a stop sequence matched) |
| `length` | `max_tokens` |
| `tool_calls` | `tool_use` |

**Usage mapping**:

| OpenAI | Anthropic |
|---|---|
| `prompt_tokens` | `input_tokens` |
| `completion_tokens` | `output_tokens` |
| — | `cache_creation_input_tokens: 0` |
| — | `cache_read_input_tokens: 0` |

### 1.6 Streaming: OpenAI SSE → Anthropic SSE

This is the most complex component. OpenAI emits flat `data: {chunk}` lines terminated by `data: [DONE]`. Anthropic uses hierarchical typed events.

**State machine**:

```python
State variables:
  block_index: int = 0          # current content block index
  active_block: str|None = None # "text" | "tool_use" | None
  message_started: bool = False
  tool_states: dict = {}        # {tool_call_index: {id, name, args_buffer}}

On each OpenAI chunk:

1. IF not message_started:
   EMIT event: message_start
     data: {type: "message_start", message: {id: "msg_...", type: "message",
            role: "assistant", content: [], model: "...",
            usage: {input_tokens: <from first chunk or estimate>}}}
   message_started = True

2. IF chunk has delta.content (text):
   IF active_block != "text":
     IF active_block is not None:
       EMIT content_block_stop (index=block_index)
       block_index += 1
     EMIT content_block_start (index=block_index, type="text")
     active_block = "text"
   EMIT content_block_delta (index=block_index, delta={type: "text_delta", text: delta.content})

3. IF chunk has delta.tool_calls:
   FOR each tc in delta.tool_calls:
     IF tc.id is present (new tool call):
       IF active_block is not None:
         EMIT content_block_stop (index=block_index)
         block_index += 1
       tool_states[tc.index] = {id: tc.id, name: tc.function.name, args: ""}
       EMIT content_block_start (index=block_index, type="tool_use",
             content_block={type: "tool_use", id: "toolu_...", name: tc.function.name})
       active_block = "tool_use"
     IF tc.function.arguments:
       tool_states[tc.index].args += tc.function.arguments
       EMIT content_block_delta (index=block_index,
             delta={type: "input_json_delta", partial_json: tc.function.arguments})

4. IF chunk has finish_reason:
   IF active_block is not None:
     EMIT content_block_stop (index=block_index)
   EMIT message_delta (delta={stop_reason: map(finish_reason)},
         usage={output_tokens: <from chunk or estimate>})
   EMIT message_stop

5. IF chunk is [DONE]:
   Ensure message_stop was emitted (guard for edge cases)
```

**Anthropic SSE format** (each event):
```
event: {event_type}
data: {json_payload}

```

### 1.7 Error Response Conversion

Backend errors must be converted to Anthropic error format, otherwise Claude Code crashes.

```
OpenAI error:
  {"error": {"message": "...", "type": "...", "code": "..."}}

Anthropic error:
  {"type": "error", "error": {"type": "{mapped_type}", "message": "..."}}
```

| HTTP Status | Anthropic error type |
|---|---|
| 400 | `invalid_request_error` |
| 401 | `authentication_error` |
| 403 | `permission_error` |
| 404 | `not_found_error` |
| 429 | `rate_limit_error` |
| 500+ | `api_error` |

Streaming errors (SSE after 200): emit `error` event then close stream.

### 1.8 Authentication & Routing

- [ ] Accept any `x-api-key` or `Authorization: Bearer` header from client
- [ ] Config file specifying backend LLM endpoint + API key
- [ ] Model name mapping table (claude-sonnet-4-20250514 → qwen3-235b-a22b, etc.)
- [ ] Passthrough: forward client API key to backend if no backend key configured

### 1.9 Infrastructure

- [ ] Python (FastAPI/Starlette), httpx (AsyncClient) for outbound requests
- [ ] Docker support (Dockerfile + docker-compose.yml)
- [ ] Minimal dependencies: fastapi, uvicorn, httpx, pyyaml, tiktoken

---

## Phase 2: Claude Code Setup & Configuration — P0

### 2.1 Usage Documentation
- [ ] How to set `ANTHROPIC_BASE_URL=http://localhost:<port>` (SDK appends `/v1/messages`)
- [ ] How to set `ANTHROPIC_API_KEY`
- [ ] Claude Code respects `ANTHROPIC_BASE_URL` (confirmed via SDK source)

### 2.2 Scripts
- [ ] `start.sh` — start proxy + optional Claude Code launch
- [ ] `install.sh` — install dependencies + generate config
- [ ] Windows `start.ps1` / `install.ps1`

### 2.3 Model Compatibility Matrix
- [ ] Test & document: Kimi 2.5, GLM5, Qwen3, vLLM
- [ ] Per-model: tool calling support, vision support, known quirks

---

## Phase 3: Protocol Completeness — P1

### 3.1 Advanced Features
- [ ] Document content blocks (`type: "document"`) — extract text or return error
- [ ] Cache control field passthrough (for backends that support it)
- [ ] Batch API
- [ ] `anthropic-beta` header handling

### 3.2 Thinking Blocks
- [ ] Request: `thinking.budget_tokens` → provider-specific reasoning param (if supported) or strip
- [ ] Response: map backend `reasoning_content` → Anthropic `thinking` content block (if available)
- [ ] Streaming: synthesize `thinking_delta` events from backend reasoning stream
- [ ] `signature_delta`: fabricate or omit (third-party models cannot produce valid signatures)

### 3.3 Robustness
- [ ] Retry logic with exponential backoff
- [ ] Request/response logging (debug mode, structured JSON logs)
- [ ] Timeout handling (configurable per-model)
- [ ] Ping events for long-running streams

---

## Phase 4: Enhancements — P2

### 4.1 Multi-Model Routing
- [ ] Auto-select model by request complexity
- [ ] Fallback chain (primary → secondary → tertiary)

### 4.2 Prompt Optimization
- [ ] System prompt patches for non-Claude models (improve tool calling accuracy)
- [ ] Model-specific prompt templates

### 4.3 Dashboard
- [ ] Request statistics, token usage, cost estimation

---

## Config Design

```yaml
# config.example.yaml
server:
  host: "0.0.0.0"
  port: 8082
  log_level: "info"       # debug | info | warning | error
  debug_log: false        # log full request/response bodies

backends:
  - name: "kimi"
    base_url: "https://api.moonshot.cn/v1"
    api_key: "${KIMI_API_KEY}"   # env var reference
    models:
      - alias: "claude-sonnet-4-20250514"
        target: "kimi-2.5"
      - alias: "claude-haiku-4-5-20251001"
        target: "kimi-2.5-mini"
    capabilities:
      tool_calling: true
      vision: true
      reasoning: false
    timeout: 300

  - name: "vllm-local"
    base_url: "http://localhost:8000/v1"
    api_key: "dummy"
    models:
      - alias: "claude-opus-4-6"
        target: "qwen3-235b-a22b"
    capabilities:
      tool_calling: true
      vision: false
      reasoning: false
    timeout: 600

# First matching alias wins
default_backend: "kimi"
```

---

## Known Pitfalls

1. **`tool_choice: "any"` → `"required"`**: OpenAI has no `"any"` value; passing through causes 400 errors
2. **`input_json_delta` fragmentation**: tool arguments arrive in fragments across chunks, must buffer per tool_call index
3. **Tool call ID format**: Claude Code may validate `toolu_` prefix; generate IDs accordingly, don't passthrough OpenAI `call_` IDs
4. **Message ID format**: generate `msg_` + random string, not passthrough `chatcmpl-`
5. **Path doubling**: if user sets `ANTHROPIC_BASE_URL=http://host/v1`, requests hit `/v1/v1/messages`
6. **`stop_sequence` vs `end_turn`**: both map from OpenAI `stop`, distinguish by checking if a stop_sequence was configured
7. **System prompt array**: Anthropic `system` can be `[{"type":"text","text":"...","cache_control":{...}}]`, must flatten + strip
8. **Streaming tool interleaving**: OpenAI can interleave chunks for multiple tool_calls via `index`; must track per-index state
9. **Usage in streaming**: OpenAI sends usage only in final chunk (with `stream_options.include_usage: true`); must request it
10. **`anthropic-version` header**: Claude Code always sends it; proxy must accept without error

---

## Tech Stack

| Component | Choice | Reason |
|---|---|---|
| Framework | FastAPI (Starlette) | Async, minimal, auto OpenAPI docs |
| HTTP Client | httpx (AsyncClient) | Streaming support, async, well-maintained |
| Deploy | Docker / bare metal | Flexible |
| Config | YAML + env vars | Simple, supports env var interpolation |
| Token counting | tiktoken | Approximation for count_tokens endpoint |
| Testing | pytest + httpx + pytest-asyncio | Async test support |

---

## Key Risks

1. **Model tool calling capability gaps** — domestic models may have subtle function calling format differences; proxy needs per-model format correction
2. **Streaming protocol complexity** — the state machine (§1.6) is the hardest part; incorrect event ordering will crash Claude Code
3. **Thinking block signatures** — Claude Code may validate `signature_delta`; third-party models cannot produce valid ones
4. **License** — this project does NOT modify or distribute Claude Code; protocol conversion only (similar to HTTP proxy)

---

## File Structure

```
openClaude/
├── README.md
├── PLAN.md
├── CLAUDE.md
├── config.example.yaml
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── proxy/
│   ├── __init__.py
│   ├── server.py                # FastAPI app, route handlers
│   ├── config.py                # YAML + env var config loading
│   ├── auth.py                  # Header translation (x-api-key → Bearer)
│   ├── models.py                # Model name mapping + capability lookup
│   ├── streaming.py             # SSE state machine (§1.6)
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── anthropic.py         # Pydantic models for Anthropic request/response
│   │   └── openai.py            # Pydantic models for OpenAI request/response
│   └── converter/
│       ├── __init__.py
│       ├── request.py           # Anthropic request → OpenAI request
│       ├── response.py          # OpenAI response → Anthropic response
│       ├── tools.py             # Tool definitions, tool_choice, tool_result
│       ├── content.py           # Content blocks (text, image, document)
│       └── errors.py            # Error format conversion
├── scripts/
│   ├── install.sh
│   ├── install.ps1
│   ├── start.sh
│   └── start.ps1
└── tests/
    ├── conftest.py
    ├── test_request_converter.py
    ├── test_response_converter.py
    ├── test_tool_converter.py
    ├── test_streaming.py
    ├── test_error_converter.py
    ├── test_integration.py       # End-to-end with mock backend
    └── fixtures/
        ├── anthropic_requests/   # Recorded Anthropic-format requests
        ├── openai_responses/     # Recorded OpenAI-format responses
        └── streaming/            # Recorded SSE event sequences
```
