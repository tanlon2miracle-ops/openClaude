# openClaude — Implementation Plan

## Background

Claude Code (npm: @anthropic-ai/claude-code) is a 12MB minified JS single file (cli.js),
hardcoded to use the Anthropic Messages API. Source code was leaked via source maps (1902 TS files, 513K lines).
Community analysis: https://github.com/liuup/claude-code-analysis

**Goal**: Without modifying Claude Code source, use an external proxy for protocol conversion,
enabling any OpenAI-compatible model (Kimi 2.5, GLM5, Qwen3, vLLM, etc.) to drive Claude Code.

---

## Phase 1: API Proxy Core - P0

### 1.1 Anthropic -> OpenAI Protocol Converter
- [ ] Implement `/v1/messages` endpoint (Anthropic Messages API)
- [ ] Request conversion: Anthropic messages -> OpenAI chat completions
  - system prompt handling (Anthropic: top-level field, OpenAI: role=system)
  - content blocks (text/image/tool_use/tool_result) -> OpenAI format
  - tool_use / tool_result bidirectional conversion
  - thinking blocks handling (map to reasoning_content or discard)
- [ ] Response conversion: OpenAI completion -> Anthropic message response
  - stop_reason mapping (stop/length/tool_calls -> end_turn/max_tokens/tool_use)
  - usage field mapping
  - tool_calls -> content blocks (tool_use)
- [ ] Streaming support: OpenAI SSE -> Anthropic SSE event conversion
  - message_start / content_block_start / content_block_delta / message_delta / message_stop
  - Handle tool_use fragmentation in streaming correctly

### 1.2 Authentication & Routing
- [ ] Accept any `x-api-key` or `Authorization` header
- [ ] Config file specifying backend LLM endpoint + API key
- [ ] Model name mapping table (claude-sonnet-4 -> qwen3-235b-a22b, etc.)

### 1.3 Infrastructure
- [ ] Python (FastAPI/Starlette) implementation, minimal dependencies
- [ ] Docker support (one-click deploy)
- [ ] Health check `/health`

---

## Phase 2: Claude Code Setup & Configuration - P0

### 2.1 Environment Variable Injection
- [ ] Docs: How to set `ANTHROPIC_BASE_URL` to point to proxy
- [ ] Docs: How to set `ANTHROPIC_API_KEY` (proxy-side validation or passthrough)
- [ ] Verify Claude Code actually respects `ANTHROPIC_BASE_URL`
  - Fallback: hosts file redirect + self-signed cert

### 2.2 Install Scripts
- [ ] `install.sh` - one-click install Claude Code + configure proxy
- [ ] `start.sh` - start proxy + claude code
- [ ] Windows `install.ps1` / `start.ps1`

### 2.3 Model Compatibility Matrix
- [ ] Test Kimi 2.5 compatibility (tool calling capability)
- [ ] Test GLM5 compatibility
- [ ] Test Qwen3 compatibility
- [ ] Test vLLM local deployment compatibility
- [ ] Document each model's tool calling limitations and workarounds

---

## Phase 3: Protocol Completeness - P1

### 3.1 Advanced Features
- [ ] `/v1/messages/count_tokens` - token counting (tiktoken approximation)
- [ ] `/v1/models` - model listing
- [ ] Cache control field handling
- [ ] Batch API (if needed)

### 3.2 Tool Calling Deep Adaptation
- [ ] Handle Claude Code built-in tool formats (Read, Write, Edit, Bash, etc.)
- [ ] Handle nested tool_result + tool_use in multi-turn conversations
- [ ] input_json_delta streaming tool parameters

### 3.3 Robustness
- [ ] Error code mapping (OpenAI 4xx/5xx -> Anthropic error format)
- [ ] Retry logic
- [ ] Request/response logging (debug mode)
- [ ] Timeout handling

---

## Phase 4: Enhancements - P2

### 4.1 Multi-Model Routing
- [ ] Auto-select model by request content/complexity
- [ ] Cheap model for plan, expensive model for code
- [ ] Fallback chain

### 4.2 Prompt Optimization
- [ ] Inject system prompt patches to improve non-Claude model tool calling accuracy
- [ ] Model-specific prompt templates

### 4.3 Dashboard
- [ ] Request statistics
- [ ] Token usage
- [ ] Cost estimation

---

## Tech Stack

| Component | Choice | Reason |
|-----------|--------|--------|
| Proxy | Python + FastAPI | Good async perf, rich ecosystem |
| Deploy | Docker / bare metal | Flexible |
| Config | YAML / env vars | Simple |
| Testing | pytest + httpx | Standard |

## Key Risks

1. **Claude Code may not respect ANTHROPIC_BASE_URL**
   - Source analysis shows it reads this env var
   - Fallback: hosts file redirect + self-signed cert

2. **Model tool calling capability gaps**
   - Domestic models may have subtle function calling format differences
   - Proxy layer needs format correction

3. **Streaming protocol differences**
   - Anthropic SSE and OpenAI SSE event formats are completely different
   - Most complex part, requires state machine handling

4. **License**
   - Claude Code is commercial license, not open source
   - This project does NOT modify or distribute Claude Code, only does protocol conversion
   - Similar to an HTTP proxy, no copyright issues

---

## File Structure (Planned)

```
openClaude/
├── README.md
├── PLAN.md
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── config.example.yaml
├── proxy/
│   ├── __init__.py
│   ├── server.py              # FastAPI entry
│   ├── converter.py           # Anthropic <-> OpenAI format conversion
│   ├── streaming.py           # Streaming SSE conversion
│   ├── models.py              # Model mapping
│   ├── auth.py                # Authentication
│   └── config.py              # Config loading
├── scripts/
│   ├── install.sh
│   ├── install.ps1
│   ├── start.sh
│   └── start.ps1
└── tests/
    ├── test_converter.py
    ├── test_streaming.py
    └── fixtures/
```
