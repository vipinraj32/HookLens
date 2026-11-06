"""Small EVM utilities shared by the analysis engine: keccak, selectors, hex helpers.

Kept free of web/database dependencies so the engine runs from the CLI as well as the API.
"""

from __future__ import annotations

import re

from Crypto.Hash import keccak as _keccak
from eth_utils import to_checksum_address

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
_HEX_RE = re.compile(r"^0x[0-9a-fA-F]*$")


def keccak(data: bytes) -> bytes:
    h = _keccak.new(digest_bits=256)
    h.update(data)
    return h.digest()


def keccak_hex(data: bytes) -> str:
    return "0x" + keccak(data).hex()


def selector(signature: str) -> str:
    return "0x" + keccak(signature.encode()).hex()[:8]


def hex_to_bytes(value: str) -> bytes:
    if not isinstance(value, str) or not _HEX_RE.match(value):
        raise ValueError("not a 0x-prefixed hex string")
    v = value[2:]
    if len(v) % 2:
        v = "0" + v
    return bytes.fromhex(v)


def word_to_address(word: str | bytes) -> str:
    b = hex_to_bytes(word) if isinstance(word, str) else word
    b = b.rjust(32, b"\x00")[-32:]
    return to_checksum_address("0x" + b[12:].hex())


def word_to_int(word: str) -> int:
    return int(word, 16) if word and word != "0x" else 0


def to_signed(value: int, bits: int) -> int:
    value &= (1 << bits) - 1
    return value - (1 << bits) if value >> (bits - 1) else value
