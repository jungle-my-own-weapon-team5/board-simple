from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from typing import Any

from app.core.config import Settings


def make_cache_key(namespace: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"{namespace}:{digest}"


def get_json_cache(settings: Settings, key: str) -> Any | None:
    client = _get_redis_client(settings.redis_url)
    if client is None:
        return None
    try:
        value = client.get(key)
        if value is None:
            return None
        return json.loads(value)
    except Exception:
        return None


def set_json_cache(settings: Settings, key: str, value: Any, ttl_seconds: int) -> None:
    if ttl_seconds <= 0:
        return
    client = _get_redis_client(settings.redis_url)
    if client is None:
        return
    try:
        payload = json.dumps(value, ensure_ascii=False, default=str)
        client.setex(key, ttl_seconds, payload)
    except Exception:
        return


@lru_cache
def _get_redis_client(redis_url: str | None):
    if not redis_url:
        return None
    try:
        from redis import Redis

        client = Redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=1, socket_timeout=1)
        client.ping()
        return client
    except Exception:
        return None
