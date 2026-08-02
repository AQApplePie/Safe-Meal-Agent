"""Safe serialization for trace inputs and outputs."""

import json
import re

from safemeal.shared.types import JsonValue, to_json_value


_SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "cookie",
    "password",
    "secret",
    "access_token",
    "refresh_token",
}


def _redact_sensitive(value: object) -> JsonValue:
    """Recursively redact credentials while preserving diagnostic evidence."""

    if isinstance(value, dict):
        return to_json_value(
            {
                key: (
                    "[REDACTED]"
                    if str(key).lower() in _SENSITIVE_KEYS
                    else _redact_sensitive(item)
                )
                for key, item in value.items()
            }
        )
    if isinstance(value, list):
        return to_json_value([_redact_sensitive(item) for item in value])
    if isinstance(value, tuple):
        return to_json_value([_redact_sensitive(item) for item in value])
    if isinstance(value, str):
        return re.sub(
            r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+",
            "Bearer [REDACTED]",
            value,
        )
    return to_json_value(value)


def safe_trace_payload(value: object, max_chars: int = 24_000) -> JsonValue:
    """Convert arbitrary values into bounded, credential-safe JSON data."""

    if hasattr(value, "model_dump"):
        value = value.model_dump()
    value = _redact_sensitive(value)
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        text = str(value)
    if len(text) <= max_chars:
        try:
            return to_json_value(json.loads(text))
        except json.JSONDecodeError:
            return text
    return {
        "truncated": True,
        "original_chars": len(text),
        "preview": text[:max_chars],
    }
