from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing_extensions import override

from .base import AsyncBaseCache, BaseCache, BaseCacheStrategy


@dataclass(frozen=True)
class _Item:
    value: str
    expire_at: datetime


class MemCache(AsyncBaseCache, BaseCache):
    """Simple Memory Cache with Expiration Support"""

    def __init__(self) -> None:
        self._cache: dict[str, _Item] = {}

    def expire(self) -> None:
        now = datetime.now(UTC)
        for key, item in list(self._cache.items()):
            if item.expire_at < now:
                self._cache.pop(key, None)

    @override
    def get(self, key: str) -> str | None:
        item = self._cache.get(key)
        if item is None:
            return None
        if item.expire_at < datetime.now(UTC):
            self._cache.pop(key, None)
            return None
        return item.value

    @override
    async def aget(self, key: str) -> str | None:
        return self.get(key)

    @override
    def set(self, key: str, value: str, ex: timedelta) -> None:
        self._cache[key] = _Item(value, datetime.now(UTC) + ex)

    @override
    async def aset(self, key: str, value: str, ex: timedelta) -> None:
        self.set(key, value, ex)

    @override
    def delete(self, key: str) -> None:
        self._cache.pop(key, None)

    @override
    async def adelete(self, key: str) -> None:
        self.delete(key)


class MemCacheStrategy(BaseCacheStrategy):
    def __init__(self) -> None:
        self._cache: MemCache | None = None

    @override
    def get_cache_storage(self) -> MemCache:
        if self._cache is None:
            self._cache = MemCache()
        return self._cache

    @override
    async def get_async_cache_storage(self) -> MemCache:
        return self.get_cache_storage()

    def cleanup(self) -> None:
        self._cache = None
