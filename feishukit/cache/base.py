import abc
from datetime import timedelta


class BaseCache(abc.ABC):
    @abc.abstractmethod
    def get(self, key: str) -> str | None:
        raise NotImplementedError

    @abc.abstractmethod
    def set(self, key: str, value: str, ex: timedelta) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def delete(self, key: str) -> None:
        raise NotImplementedError


class AsyncBaseCache(abc.ABC):
    @abc.abstractmethod
    async def aget(self, key: str) -> str | None:
        raise NotImplementedError

    @abc.abstractmethod
    async def aset(self, key: str, value: str, ex: timedelta) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    async def adelete(self, key: str) -> None:
        raise NotImplementedError


class BaseCacheStrategy(abc.ABC):
    @abc.abstractmethod
    def get_cache_storage(self) -> BaseCache:
        """Get the cache storage instance used in sync context

        raise CacheUnsupportedError if the strategy does not support sync usage
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def get_async_cache_storage(self) -> AsyncBaseCache:
        """Get the cache storage instance used in async context

        raise CacheUnsupportedError if the strategy does not support async usage
        """
        raise NotImplementedError
