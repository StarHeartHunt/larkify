# 安装

!!! tip

    larkify 需要 Python 3.11+（来自 httpx2 的要求）。

## 基础安装

=== "pip"

    ```bash
    pip install larkify
    ```

=== "uv"

    ```bash
    uv add larkify
    ```

=== "poetry"

    ```bash
    poetry add larkify
    ```

=== "pdm"

    ```bash
    pdm add larkify
    ```

## 可选依赖

| 依赖 | 用途 |
| --- | --- |
| `crypto` | 解密加密的事件和回调 |
| `ws` | 长连接 |
| `redis` | 多进程共享 token 缓存 |
| `http2` | HTTP/2 |
| `all` | 以上全部 |

=== "pip"

    ```bash
    pip install "larkify[all]"
    ```

=== "uv"

    ```bash
    uv add "larkify[all]"
    ```

=== "poetry"

    ```bash
    poetry add "larkify[all]"
    ```

=== "pdm"

    ```bash
    pdm add "larkify[all]"
    ```
