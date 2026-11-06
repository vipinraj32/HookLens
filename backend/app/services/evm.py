"""EVM utilities for the API: re-exports the engine helpers plus user-input validators."""

from __future__ import annotations

import re

from eth_utils import is_hex_address, to_checksum_address

from app.errors import AppError
from hooklens.evm import (  # noqa: F401  (re-exported for existing callers)
    ZERO_ADDRESS,
    hex_to_bytes,
    keccak,
    keccak_hex,
    selector,
    to_signed,
    word_to_address,
    word_to_int,
)


def validate_address(value: str, *, field: str = "address") -> str:
    """Validate and checksum an address. Rejects malformed input and the zero address.

    Mixed-case input must carry a valid EIP-55 checksum; all-lower/all-upper is accepted.
    """
    if not isinstance(value, str):
        raise AppError("invalid_address", f"{field} must be a string.", status_code=422)
    v = value.strip()
    if not is_hex_address(v):
        raise AppError("invalid_address", f"{field} is not a valid 20-byte hex address.", status_code=422)
    body = v[2:]
    if body != body.lower() and body != body.upper() and to_checksum_address(v) != v:
        raise AppError("invalid_checksum", f"{field} has an invalid EIP-55 checksum.", status_code=422)
    cs = to_checksum_address(v)
    if cs == ZERO_ADDRESS:
        raise AppError("zero_address", f"{field} is the zero address.", status_code=422)
    return cs


def validate_pool_id(value: str) -> str:
    v = value.strip().lower()
    if not re.fullmatch(r"0x[0-9a-f]{64}", v):
        raise AppError("invalid_pool_id", "pool_id must be a 32-byte hex string (0x + 64 hex chars).", status_code=422)
    return v
