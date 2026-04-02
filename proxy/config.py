import os
import re
from pathlib import Path
from typing import Any

import yaml

_ENV_VAR_PATTERN = re.compile(r"\$\{(\w+)}")

_config: dict[str, Any] | None = None


def _resolve_env_vars(value: Any) -> Any:
    if isinstance(value, str):
        def _replace(m: re.Match) -> str:
            return os.environ.get(m.group(1), "")
        return _ENV_VAR_PATTERN.sub(_replace, value)
    if isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env_vars(v) for v in value]
    return value


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    global _config
    if _config is not None and path is None:
        return _config

    if path is None:
        for candidate in ("config.yaml", "config.yml", "config.example.yaml"):
            p = Path(candidate)
            if p.exists():
                path = p
                break
        if path is None:
            path = Path("config.example.yaml")

    with open(path) as f:
        raw = yaml.safe_load(f)

    _config = _resolve_env_vars(raw)
    return _config


def get_config() -> dict[str, Any]:
    if _config is None:
        return load_config()
    return _config
