import json
import logging
import re
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from proxy.auth import build_backend_headers, extract_api_key
from proxy.config import get_config, load_config
from proxy.converter.errors import convert_openai_error, format_stream_error, to_anthropic_error
from proxy.converter.request import convert_request
from proxy.converter.response import convert_response
from proxy.models import list_models, resolve_model
from proxy.streaming import transform_sse_stream

logger = logging.getLogger("openClaude")

_http_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _http_client
    load_config()
    _http_client = httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0))
    cfg = get_config()
    log_level = cfg.get("server", {}).get("log_level", "info").upper()
    logging.basicConfig(level=getattr(logging, log_level, logging.INFO))
    logger.info("openClaude proxy started")
    yield
    await _http_client.aclose()
    _http_client = None


app = FastAPI(title="openClaude", lifespan=lifespan)


_DOUBLE_V1 = re.compile(r"/v1/v1/")
_DOUBLE_SLASH = re.compile(r"//+")


@app.middleware("http")
async def normalize_path(request: Request, call_next):
    path = request.scope["path"]
    path = _DOUBLE_V1.sub("/v1/", path)
    path = _DOUBLE_SLASH.sub("/", path)
    path = path.rstrip("/") or "/"
    request.scope["path"] = path
    return await call_next(request)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/v1/models")
async def models_list():
    models = list_models()
    data = []
    for m in models:
        data.append({
            "id": m["alias"],
            "object": "model",
            "created": 0,
            "owned_by": m["backend"],
        })
    return {"object": "list", "data": data}


@app.post("/v1/messages/count_tokens")
async def count_tokens(request: Request):
    try:
        body = await request.json()
    except Exception:
        return to_anthropic_error(400, "Invalid JSON body")

    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
    except Exception:
        enc = None

    total = 0
    system = body.get("system")
    if system:
        text = system if isinstance(system, str) else json.dumps(system)
        total += len(enc.encode(text)) if enc else len(text) // 4

    for msg in body.get("messages", []):
        content = msg.get("content", "")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = json.dumps(content)
        else:
            text = str(content)
        total += len(enc.encode(text)) if enc else len(text) // 4

    tools = body.get("tools")
    if tools:
        text = json.dumps(tools)
        total += len(enc.encode(text)) if enc else len(text) // 4

    return {"input_tokens": total}


@app.post("/v1/messages")
async def messages(request: Request):
    try:
        body = await request.json()
    except Exception:
        return to_anthropic_error(400, "Invalid JSON body")

    anthropic_model = body.get("model", "")
    try:
        target_model, backend_cfg = resolve_model(anthropic_model)
    except ValueError as e:
        return to_anthropic_error(400, str(e))

    client_key = extract_api_key(request)
    headers = build_backend_headers(client_key, backend_cfg)
    openai_body = convert_request(body, target_model)

    base_url = backend_cfg.get("base_url", "").rstrip("/")
    url = f"{base_url}/chat/completions"
    timeout = backend_cfg.get("timeout", 300)

    cfg = get_config()
    debug = cfg.get("server", {}).get("debug_log", False)
    if debug:
        logger.debug("Request to %s: %s", url, json.dumps(openai_body, ensure_ascii=False)[:2000])

    is_stream = body.get("stream", False)

    if is_stream:
        return await _handle_streaming(
            url, headers, openai_body, anthropic_model,
            body.get("stop_sequences"), timeout, debug,
        )
    else:
        return await _handle_non_streaming(
            url, headers, openai_body, anthropic_model,
            body.get("stop_sequences"), timeout, debug,
        )


async def _handle_non_streaming(
    url: str,
    headers: dict[str, str],
    openai_body: dict[str, Any],
    anthropic_model: str,
    stop_sequences: list[str] | None,
    timeout: int,
    debug: bool,
) -> JSONResponse:
    try:
        resp = await _http_client.post(
            url, json=openai_body, headers=headers,
            timeout=httpx.Timeout(float(timeout), connect=10.0),
        )
    except httpx.TimeoutException:
        return to_anthropic_error(504, "Backend request timed out")
    except httpx.HTTPError as e:
        return to_anthropic_error(502, f"Backend connection error: {e}")

    if resp.status_code != 200:
        try:
            err_body = resp.json()
        except Exception:
            err_body = resp.text
        return convert_openai_error(resp.status_code, err_body)

    try:
        openai_resp = resp.json()
    except Exception:
        return to_anthropic_error(502, "Invalid JSON from backend")

    if debug:
        logger.debug("Response from backend: %s", json.dumps(openai_resp, ensure_ascii=False)[:2000])

    anthropic_resp = convert_response(openai_resp, anthropic_model, stop_sequences)
    return JSONResponse(content=anthropic_resp)


async def _handle_streaming(
    url: str,
    headers: dict[str, str],
    openai_body: dict[str, Any],
    anthropic_model: str,
    stop_sequences: list[str] | None,
    timeout: int,
    debug: bool,
) -> StreamingResponse:
    async def event_generator():
        try:
            async with _http_client.stream(
                "POST", url, json=openai_body, headers=headers,
                timeout=httpx.Timeout(float(timeout), connect=10.0),
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    try:
                        err = json.loads(body)
                        msg = err.get("error", {}).get("message", body.decode() if isinstance(body, bytes) else str(body))
                    except Exception:
                        msg = body.decode() if isinstance(body, bytes) else str(body)
                    yield f"event: error\ndata: {format_stream_error(msg)}\n\n"
                    return

                async for line in resp.aiter_lines():
                    yield line.encode("utf-8") if isinstance(line, str) else line
                    yield b"\n"

        except httpx.TimeoutException:
            yield f"event: error\ndata: {format_stream_error('Backend request timed out')}\n\n"
        except httpx.HTTPError as e:
            yield f"event: error\ndata: {format_stream_error(f'Backend connection error: {e}')}\n\n"

    async def anthropic_event_generator():
        async for event_str in transform_sse_stream(
            event_generator(), anthropic_model, stop_sequences
        ):
            yield event_str

    return StreamingResponse(
        anthropic_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    import uvicorn
    cfg = load_config()
    server_cfg = cfg.get("server", {})
    uvicorn.run(
        "proxy.server:app",
        host=server_cfg.get("host", "0.0.0.0"),
        port=server_cfg.get("port", 8082),
        log_level=server_cfg.get("log_level", "info"),
    )
