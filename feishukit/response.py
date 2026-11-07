from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import asynccontextmanager, contextmanager
from functools import cached_property
from typing import Any, Generic, cast
from typing_extensions import TypeForm, TypeVar

import httpx2
from pydantic import BaseModel, TypeAdapter

from .exception import RequestError, RequestTimeout
from .utils import UNSET, parse_file_name

# Covariant so that `Response[ListChatResponse]` matches `Response[Page[Chat]]`.
MT = TypeVar("MT", covariant=True, default=Any)


class Response(Generic[MT]):
    """A wrapper around httpx2.Response that provides data model validation.

    Feishu wraps results in `{"code": 0, "msg": "...", "data": {...}}`. With the
    default `data_key` the model describes the `data` object. `data_key=None` is
    for the few APIs returning their fields at the top level.
    """

    def __init__(
        self,
        response: httpx2.Response,
        data_model: TypeForm[MT],  # pyright: ignore[reportGeneralTypeIssues]
        *,
        data_key: str | None = "data",
    ):
        self._response = response
        self._data_model = data_model
        self._data_key = data_key
        self._cached_parsed_data: Any = UNSET

    def __repr__(self) -> str:
        return (
            f"Response({self.status_code}, code={self.code}, "
            f"data_model={self._data_model})"
        )

    @property
    def raw_request(self) -> httpx2.Request:
        return self._response.request

    @property
    def raw_response(self) -> httpx2.Response:
        return self._response

    @property
    def status_code(self) -> int:
        return self._response.status_code

    @property
    def reason_phrase(self) -> str:
        return self._response.reason_phrase

    @property
    def is_success(self) -> bool:
        return self._response.is_success

    @property
    def is_client_error(self) -> bool:
        return self._response.is_client_error

    @property
    def is_server_error(self) -> bool:
        return self._response.is_server_error

    @property
    def is_error(self) -> bool:
        return self._response.is_error

    def raise_for_status(self) -> None:
        self._response.raise_for_status()

    @property
    def headers(self) -> httpx2.Headers:
        return self._response.headers

    @property
    def url(self) -> httpx2.URL:
        return self._response.url

    @property
    def content(self) -> bytes:
        return self._response.content

    @property
    def text(self) -> str:
        return self._response.text

    def json(self, **kwargs: Any) -> Any:
        return self._response.json(**kwargs)

    @cached_property
    def _envelope(self) -> Mapping[str, Any]:
        """The decoded JSON object, or nothing for files and unread streams."""
        if self._data_model is bytes and "json" not in self.headers.get(
            "content-type", ""
        ):
            return {}
        try:
            body = self._response.json()
        except (ValueError, httpx2.ResponseNotRead):
            return {}
        return body if isinstance(body, dict) else {}

    @property
    def code(self) -> int | None:
        """Business status code. Zero, or absent, means success."""
        code = self._envelope.get("code")
        try:
            return None if code is None else int(code)
        except (TypeError, ValueError):
            return None

    @property
    def msg(self) -> str | None:
        # `error` is an object on API responses, and a string on OAuth ones.
        for key in ("msg", "error_description", "error"):
            value = self._envelope.get(key)
            if value and isinstance(value, str):
                return value
        return None

    @property
    def error(self) -> Mapping[str, Any]:
        """Diagnostics of a failed call: `troubleshooter`, `violations`, ..."""
        error = self._envelope.get("error")
        return error if isinstance(error, dict) else {}

    @property
    def log_id(self) -> str | None:
        """Log id to quote when asking Feishu support about this request."""
        return self.headers.get("x-tt-logid") or self.error.get("log_id")

    @property
    def file_name(self) -> str | None:
        """Name of the downloaded file, from `Content-Disposition`."""
        return parse_file_name(self.headers.get("content-disposition"))

    @property
    def parsed_data(self) -> MT:
        if self._cached_parsed_data is UNSET:
            self._cached_parsed_data = self._parse()
        return self._cached_parsed_data

    def _parse(self) -> Any:
        if self._data_model is bytes:
            return self.content
        if self._data_model is None:
            return None

        body = self._envelope or self.json()
        if self._data_key is not None:
            # Some APIs omit `data` altogether when there is nothing to return.
            body = body.get(self._data_key)
            if body is None:
                body = {}
        if self._data_model is Any:
            return body
        if isinstance(self._data_model, type) and issubclass(
            self._data_model, BaseModel
        ):
            return self._data_model.model_validate(body)
        return cast(Any, TypeAdapter(self._data_model)).validate_python(body)

    @contextmanager
    def _catch_and_close(self):
        try:
            yield
        except httpx2.TimeoutException as e:
            raise RequestTimeout(e) from e
        except Exception as e:
            raise RequestError(e) from e
        finally:
            self._response.close()

    @asynccontextmanager
    async def _acatch_and_close(self):
        try:
            yield
        except httpx2.TimeoutException as e:
            raise RequestTimeout(e) from e
        except Exception as e:
            raise RequestError(e) from e
        finally:
            await self._response.aclose()

    def iter_bytes(self, chunk_size: int | None = None) -> Iterator[bytes]:
        with self._catch_and_close():
            yield from self._response.iter_bytes(chunk_size=chunk_size)

    def iter_raw(self, chunk_size: int | None = None) -> Iterator[bytes]:
        with self._catch_and_close():
            yield from self._response.iter_raw(chunk_size=chunk_size)

    async def aiter_bytes(self, chunk_size: int | None = None) -> AsyncIterator[bytes]:
        async with self._acatch_and_close():
            async for chunk in self._response.aiter_bytes(chunk_size=chunk_size):
                yield chunk

    async def aiter_raw(self, chunk_size: int | None = None) -> AsyncIterator[bytes]:
        async with self._acatch_and_close():
            async for chunk in self._response.aiter_raw(chunk_size=chunk_size):
                yield chunk
