from typing import Any

from fastapi import Request


def extract_api_key(request: Request) -> str | None:
    key = request.headers.get("x-api-key")
    if key:
        return key
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def build_backend_headers(client_key: str | None, backend_cfg: dict[str, Any]) -> dict[str, str]:
    api_key = backend_cfg.get("api_key") or client_key or ""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    custom = backend_cfg.get("headers")
    if isinstance(custom, dict):
        headers.update(custom)
    return headers
