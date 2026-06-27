#!/usr/bin/env python3
"""
Gera um par de chaves VAPID (curva P-256) já no formato base64url que
.env e o navegador esperam — sem precisar lidar com arquivos PEM manualmente.

Uso:
    pip install cryptography
    python3 deploy/generate_vapid_keys.py
"""
import base64

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def main():
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()

    private_numbers = private_key.private_numbers()
    private_value = private_numbers.private_value
    private_bytes = private_value.to_bytes(32, byteorder="big")

    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )  # 65 bytes: 0x04 + X(32) + Y(32) — formato que o navegador espera em applicationServerKey

    print("Adicione isto ao seu .env:\n")
    print(f"VAPID_PRIVATE_KEY={b64url(private_bytes)}")
    print(f"VAPID_PUBLIC_KEY={b64url(public_bytes)}")


if __name__ == "__main__":
    main()
