from functools import cached_property
from typing import TYPE_CHECKING, TypeVar

from .auth import BaseAuthStrategy
from .core import FeishuCore

if TYPE_CHECKING:
    from .rest import RestNamespace

A = TypeVar("A", bound=BaseAuthStrategy)
AS = TypeVar("AS", bound=BaseAuthStrategy)


class Feishu(FeishuCore[A]):
    """Feishu (and Lark) open platform client.

    ```python
    feishu = Feishu(AppAuthStrategy("cli_xxx", "secret"))
    resp = feishu.rest.im.v1.message.create(
        receive_id_type="open_id",
        receive_id="ou_xxx",
        msg_type="text",
        content='{"text": "hello"}',
    )
    resp.parsed_data.message_id
    ```

    Pass `base_url=LARK_BASE_URL` to talk to Lark instead of Feishu.
    """

    # copy client with other auth
    def with_auth(self, auth: AS) -> "Feishu[AS]":
        return Feishu(auth=auth, config=self.config.copy())

    # rest api
    @cached_property
    def rest(self) -> "RestNamespace":
        from .rest import RestNamespace

        return RestNamespace(self)
