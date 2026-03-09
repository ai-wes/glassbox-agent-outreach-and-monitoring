from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

import redis

from pr_monitor_app.config import settings


@dataclass(frozen=True)
class StateStore:
    _client: redis.Redis

    @classmethod
    def from_settings(cls) -> "StateStore":
        r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        return cls(_client=r)

    def get_str(self, key: str) -> Optional[str]:
        v = self._client.get(key)
        return v

    def set_str(self, key: str, value: str, *, ex_seconds: int | None = None) -> None:
        self._client.set(key, value, ex=ex_seconds)

    def incr_with_ttl(self, key: str, ttl_seconds: int) -> int:
        pipe = self._client.pipeline()
        pipe.incr(key, 1)
        pipe.expire(key, ttl_seconds)
        val, _ = pipe.execute()
        return int(val)

    def sadd(self, key: str, member: str, ttl_seconds: int) -> int:
        pipe = self._client.pipeline()
        pipe.sadd(key, member)
        pipe.expire(key, ttl_seconds)
        added, _ = pipe.execute()
        return int(added)

    def get_json(self, key: str) -> Optional[dict]:
        v = self.get_str(key)
        if not v:
            return None
        try:
            return json.loads(v)
        except Exception:
            return None

    def set_json(self, key: str, value: dict, *, ex_seconds: int | None = None) -> None:
        self.set_str(key, json.dumps(value, ensure_ascii=False), ex_seconds=ex_seconds)

    def acquire_lock(self, key: str, ttl_seconds: int) -> bool:
        """Best-effort distributed lock using SET NX EX."""
        try:
            return bool(self._client.set(key, "1", nx=True, ex=ttl_seconds))
        except Exception:
            return False

    def release_lock(self, key: str) -> None:
        try:
            self._client.delete(key)
        except Exception:
            pass
