"""Decryption and signing of event deliveries.

https://open.feishu.cn/document/server-docs/event-subscription-guide/event-subscription-configure-/encrypt-key-encryption-configuration-case
"""

import base64
import hashlib
import hmac

from larkify.exception import WebhookError, WebhookVerificationFailed

_BLOCK_SIZE = 16


def _cipher_module():
    try:
        from cryptography.hazmat.primitives import ciphers, padding
        from cryptography.hazmat.primitives.ciphers import algorithms, modes
    except ImportError:
        raise WebhookError(
            "Encrypted events need `cryptography`, "
            "install it with `pip install larkify[crypto]`"
        ) from None
    return ciphers, padding, algorithms, modes


def decrypt(encrypt_key: str, encrypted: str) -> bytes:
    """Decrypt the `encrypt` field of a delivery.

    The key is the SHA-256 of the Encrypt Key, the first block is the IV, and the
    plaintext is AES-256-CBC with PKCS#7 padding.
    """
    ciphers, padding, algorithms, modes = _cipher_module()
    try:
        raw = base64.b64decode(encrypted, validate=True)
    except ValueError as e:
        raise WebhookVerificationFailed("encrypted payload is not base64") from e
    if len(raw) < _BLOCK_SIZE * 2 or len(raw) % _BLOCK_SIZE:
        raise WebhookVerificationFailed("invalid ciphertext length")

    key = hashlib.sha256(encrypt_key.encode()).digest()
    cipher = ciphers.Cipher(algorithms.AES(key), modes.CBC(raw[:_BLOCK_SIZE]))
    decryptor = cipher.decryptor()
    padded = decryptor.update(raw[_BLOCK_SIZE:]) + decryptor.finalize()

    unpadder = padding.PKCS7(_BLOCK_SIZE * 8).unpadder()
    try:
        return unpadder.update(padded) + unpadder.finalize()
    except ValueError as e:
        raise WebhookVerificationFailed("invalid padding, wrong Encrypt Key?") from e


def encrypt(encrypt_key: str, plaintext: bytes, iv: bytes) -> str:
    """The inverse of `decrypt`, for producing test deliveries."""
    ciphers, padding, algorithms, modes = _cipher_module()
    key = hashlib.sha256(encrypt_key.encode()).digest()
    padder = padding.PKCS7(_BLOCK_SIZE * 8).padder()
    padded = padder.update(plaintext) + padder.finalize()
    encryptor = ciphers.Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(iv + ciphertext).decode()


def sign(encrypt_key: str, timestamp: str, nonce: str, body: bytes) -> str:
    """Compute the `X-Lark-Signature` of a delivery."""
    content = (timestamp + nonce + encrypt_key).encode() + body
    return hashlib.sha256(content).hexdigest()


def verify(
    encrypt_key: str, timestamp: str, nonce: str, body: bytes, signature: str
) -> bool:
    """Check the `X-Lark-Signature` of a delivery, in constant time."""
    return hmac.compare_digest(sign(encrypt_key, timestamp, nonce, body), signature)
