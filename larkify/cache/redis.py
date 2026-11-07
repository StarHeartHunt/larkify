from datetime import timedelta
from typing import TYPE_CHECKING, Any, NoReturn
from typing_extensions import override

from larkify.exception import CacheUnsupportedError

from .base import AsyncBaseCache, BaseCache, BaseCacheStrategy

if TYPE_CHECKING:
    from redis import Redis
    from redis.asyncio import Redis as AsyncRedis


def _ensure_str_or_none(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if value is None:
        return None
    raise RuntimeError(f"Unexpected redis value {value!r} with type {type(value)}")


class RedisCache(BaseCache):
    def __init__(self, client: "Redis", prefix: str | None = None) -> None:
        self.client = client
        self.prefix = prefix

    def _get_key(self, key: str) -> str:
        return f"{self.prefix}:{key}" if self.prefix is not None else key

    @override
    def get(self, key: str) -> str | None:
        return _ensure_str_or_none(self.client.get(self._get_key(key)))

    @override
    def set(self, key: str, value: str, ex: timedelta) -> None:
        self.client.set(self._get_key(key), value, ex)

    @override
    def delete(self, key: str) -> None:
        self.client.delete(self._get_key(key))


class AsyncRedisCache(AsyncBaseCache):
    def __init__(self, client: "AsyncRedis", prefix: str | None = None) -> None:
        self.client = client
        self.prefix = prefix

    def _get_key(self, key: str) -> str:
        return f"{self.prefix}:{key}" if self.prefix is not None else key

    @override
    async def aget(self, key: str) -> str | None:
        return _ensure_str_or_none(await self.client.get(self._get_key(key)))

    @override
    async def aset(self, key: str, value: str, ex: timedelta) -> None:
        await self.client.set(self._get_key(key), value, ex)

    @override
    async def adelete(self, key: str) -> None:
        await self.client.delete(self._get_key(key))


class RedisCacheStrategy(BaseCacheStrategy):
    def __init__(self, client: "Redis", prefix: str | None = None) -> None:
        self.client = client
        self.prefix = prefix.removesuffix(":") if prefix else None

    @override
    def get_cache_storage(self) -> RedisCache:
        return RedisCache(self.client, self.prefix)

    @override
    async def get_async_cache_storage(self) -> NoReturn:
        raise CacheUnsupportedError(
            "Sync redis cache strategy does not support async usage"
        )


class AsyncRedisCacheStrategy(BaseCacheStrategy):
    def __init__(self, client: "AsyncRedis", prefix: str | None = None) -> None:
        self.client = client
        self.prefix = prefix.removesuffix(":") if prefix else None

    @override
    def get_cache_storage(self) -> NoReturn:
        raise CacheUnsupportedError(
            "Async redis cache strategy does not support sync usage"
        )

    @override
    async def get_async_cache_storage(self) -> AsyncRedisCache:
        return AsyncRedisCache(self.client, self.prefix)
