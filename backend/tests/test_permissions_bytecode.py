from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from hooklens.analyzers import permissions_generated as gen
from hooklens.analyzers.bytecode import analyze_bytecode, disassemble, split_metadata
from hooklens.analyzers.permissions import decode, is_valid_hook_address, summarize

BACKEND = Path(__file__).resolve().parents[1]


def test_generated_permissions_in_sync_with_v4_core() -> None:
    if not (BACKEND.parent / "contracts" / "lib" / "v4-periphery" / "lib" / "v4-core").exists():
        pytest.skip("v4-core submodule not checked out")
    if not (BACKEND.parent / "contracts" / "out" / "IHooks.sol" / "IHooks.json").exists():
        # The generator reads the compiled IHooks selectors; CI runs this check in the contracts job after forge build.
        pytest.skip("contracts not built (run forge build in contracts/)")
    r = subprocess.run(
        [sys.executable, "scripts/gen_permissions.py", "--check"], cwd=BACKEND, capture_output=True, text=True
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_flag_table_matches_v4_core_layout() -> None:
    bits = {f[0]: f[1] for f in gen.FLAGS}
    assert bits["BEFORE_INITIALIZE"] == 13
    assert bits["AFTER_REMOVE_LIQUIDITY_RETURNS_DELTA"] == 0
    assert gen.ALL_HOOK_MASK == (1 << 14) - 1
    assert len(gen.FLAGS) == 14


def test_decode_fixture_addresses() -> None:
    # OracleGatedWithdrawalHook was mined with only BEFORE_REMOVE_LIQUIDITY (bit 9).
    s = summarize(decode("0x9d536C7335f6ca4D20384AaF7F655eb364B00200"))
    assert s["enabled_flags"] == ["BEFORE_REMOVE_LIQUIDITY"]
    s = summarize(decode("0x" + "0" * 36 + "3fff"))
    assert len(s["enabled_flags"]) == 14


def test_return_delta_requires_base_flag() -> None:
    # AFTER_SWAP_RETURNS_DELTA (bit 2) without AFTER_SWAP (bit 6) is invalid in Hooks.isValidHookAddress.
    ok, reason = is_valid_hook_address("0x" + "0" * 39 + "4")
    assert not ok and reason
    ok, _ = is_valid_hook_address("0x" + "0" * 38 + "44")
    assert ok


def test_disassembler_and_metadata() -> None:
    # PUSH1 0x80 PUSH1 0x40 MSTORE CALLER DELEGATECALL STOP + fake CBOR tail
    code = bytes.fromhex("6080604052" + "33" + "f4" + "00")
    ops = disassemble(code)
    assert [o.op for o in ops][:4] == ["PUSH1", "PUSH1", "MSTORE", "CALLER"]
    facts = analyze_bytecode(code)
    assert facts.has_delegatecall and not facts.has_selfdestruct
    body, meta = split_metadata(code)
    assert body == code and meta is None
