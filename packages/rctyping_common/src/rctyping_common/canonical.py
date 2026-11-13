"""Canonical JSON encoding (RFC 8785 inspired).

Guarantees deterministic byte serialization across different platforms
and language runtimes for cryptographic signature verification.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any


def _normalize_item(item: Any) -> Any:
    """Normalize Python types into JSON-compatible primitives recursively."""
    if item is None:
        return None
    if isinstance(item, bool):
        return item
    if isinstance(item, int):
        return item
    if isinstance(item, float):
        if math.isnan(item) or math.isinf(item):
            raise ValueError(f"Non-finite float value not permitted in canonical JSON: {item}")
        # Format floats consistently without superfluous trailing zeros if integer equivalent
        # RFC 8785 uses ECMAScript Number.prototype.toString:
        if item.is_integer():
            return int(item)
        # Round float representation to avoid platform-specific tiny precision drift
        return round(item, 10)
    if isinstance(item, str):
        return item
    if isinstance(item, (list, tuple)):
        return [_normalize_item(x) for x in item]
    if isinstance(item, dict):
        # Sort keys lexicographically
        return {str(k): _normalize_item(v) for k, v in sorted(item.items(), key=lambda kv: str(kv[0]))}
    # For objects with model_dump or to_dict
    if hasattr(item, "model_dump"):
        return _normalize_item(item.model_dump(mode="json"))
    if hasattr(item, "to_dict"):
        return _normalize_item(item.to_dict())
    raise TypeError(f"Unsupported type for canonical JSON: {type(item).__name__}")


def canonical_json_dumps(data: Any) -> bytes:
    """Serialize a Python dictionary or model into deterministic canonical JSON bytes.

    Features:
    - Keys sorted lexicographically
    - No whitespace between tokens (separators=(',', ':'))
    - Strict UTF-8 encoding
    - Escaping special chars without escaping forward slashes
    """
    normalized = _normalize_item(data)
    json_str = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return json_str.encode("utf-8")


def canonical_json_hash(data: Any) -> str:
    """Calculate the hex-encoded SHA-256 of canonical JSON data."""
    canonical_bytes = canonical_json_dumps(data)
    return hashlib.sha256(canonical_bytes).hexdigest()
