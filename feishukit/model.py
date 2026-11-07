from typing import Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class FeishuModel(BaseModel):
    """Base class of every generated model.

    The models come from documentation rather than a formal schema, so they are
    deliberately forgiving: unknown fields are kept instead of rejected, and
    numbers are accepted where the docs say string.

    `defer_build` postpones the validator build to first use. There are tens of
    thousands of models and most programs touch a handful of them.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="allow",
        protected_namespaces=(),
        coerce_numbers_to_str=True,
        defer_build=True,
    )


@runtime_checkable
class Page(Protocol[T]):
    """Response data of a paginated API whose items can be located statically."""

    @property
    def page_items(self) -> list[T]: ...
