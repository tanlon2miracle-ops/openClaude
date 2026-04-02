from typing import Any

from proxy.config import get_config


def _build_index() -> tuple[dict[str, tuple[str, dict]], dict[str, dict]]:
    """Build alias→(target_model, backend_cfg) map and name→backend_cfg map."""
    cfg = get_config()
    alias_map: dict[str, tuple[str, dict]] = {}
    backend_map: dict[str, dict] = {}
    for backend in cfg.get("backends", []):
        backend_map[backend["name"]] = backend
        for m in backend.get("models", []):
            if m["alias"] not in alias_map:
                alias_map[m["alias"]] = (m["target"], backend)
    return alias_map, backend_map


def resolve_model(anthropic_model: str) -> tuple[str, dict[str, Any]]:
    alias_map, backend_map = _build_index()
    if anthropic_model in alias_map:
        target, backend = alias_map[anthropic_model]
        return target, backend

    cfg = get_config()
    default_name = cfg.get("default_backend")
    if default_name and default_name in backend_map:
        return anthropic_model, backend_map[default_name]

    backends = cfg.get("backends", [])
    if backends:
        return anthropic_model, backends[0]

    raise ValueError(f"No backend configured for model: {anthropic_model}")


def get_capabilities(backend_cfg: dict[str, Any]) -> dict[str, bool]:
    return backend_cfg.get("capabilities", {
        "tool_calling": True,
        "vision": False,
        "reasoning": False,
    })


def list_models() -> list[dict[str, Any]]:
    cfg = get_config()
    result = []
    for backend in cfg.get("backends", []):
        for m in backend.get("models", []):
            result.append({
                "alias": m["alias"],
                "target": m["target"],
                "backend": backend["name"],
                "capabilities": backend.get("capabilities", {}),
            })
    return result
