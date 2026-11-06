"""Contract resolution pinned to a block: code, code hash, proxy relationship and source."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.analyzers.bytecode import EIP1167_PREFIX, analyze_bytecode, code_hash
from app.chains import ChainConfig
from app.errors import AppError
from app.services.evm import ZERO_ADDRESS, hex_to_bytes, selector, validate_address, word_to_address
from app.services.rpc import RpcClient
from app.services.sources import EtherscanProvider, LocalArtifactProvider, SourceResult

log = logging.getLogger(__name__)

EIP1967_IMPLEMENTATION_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
EIP1967_ADMIN_SLOT = "0xb53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103"
EIP1967_BEACON_SLOT = "0xa3f0ad74e5423aebfd80d3ef4346578335a9a72aeaee59ff6cb3582b35133d50"
OZ_LEGACY_IMPLEMENTATION_SLOT = "0x7050c9e0f4ca769c69bd3a8ef740bc37934f8e2c036e5a723fd8ee048ed3f8c3"


@dataclass
class ProxyInfo:
    is_proxy: bool = False
    kind: str | None = None  # eip1967 | eip1967-beacon | eip1167 | oz-legacy | eip897
    implementation: str | None = None
    admin: str | None = None
    beacon: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    unresolved_reason: str | None = None


@dataclass
class ResolvedContract:
    chain_id: int
    address: str
    block_number: int
    block_hash: str
    block_timestamp: int
    runtime_code: bytes
    runtime_code_hash: str
    proxy: ProxyInfo
    implementation_code: bytes | None
    implementation_code_hash: str | None
    source: SourceResult  # source of the analysed logic (implementation when proxied)
    proxy_source: SourceResult | None  # source of the proxy itself when proxied
    source_status: str
    notes: list[str] = field(default_factory=list)

    @property
    def logic_code(self) -> bytes:
        return self.implementation_code or self.runtime_code

    def provenance(self) -> dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "address": self.address,
            "block_number": self.block_number,
            "block_hash": self.block_hash,
            "block_timestamp": self.block_timestamp,
            "runtime_code_hash": self.runtime_code_hash,
            "code_size": len(self.runtime_code),
            "proxy": {
                "is_proxy": self.proxy.is_proxy,
                "kind": self.proxy.kind,
                "implementation": self.proxy.implementation,
                "implementation_code_hash": self.implementation_code_hash,
                "admin": self.proxy.admin,
                "beacon": self.proxy.beacon,
                "slots": self.proxy.evidence,
                "unresolved_reason": self.proxy.unresolved_reason,
            },
            "source": {
                "status": self.source_status,
                "provider": self.source.bundle.provider if self.source.bundle else None,
                "contract_name": self.source.contract_name,
                "compiler_version": self.source.compiler_version,
                "bytecode_match": self.source.bytecode_match,
                "notes": self.source.notes,
            },
            "notes": self.notes,
        }


def _slot_address(rpc: RpcClient, address: str, slot: str, block: int) -> str | None:
    word = rpc.get_storage_at(address, slot, block)
    try:
        a = word_to_address(word)
    except ValueError:
        return None
    return None if a == ZERO_ADDRESS else a


def detect_proxy(rpc: RpcClient, address: str, code: bytes, block: int) -> ProxyInfo:
    info = ProxyInfo()
    impl = _slot_address(rpc, address, EIP1967_IMPLEMENTATION_SLOT, block)
    admin = _slot_address(rpc, address, EIP1967_ADMIN_SLOT, block)
    beacon = _slot_address(rpc, address, EIP1967_BEACON_SLOT, block)
    info.evidence = {
        "eip1967_implementation_slot": impl,
        "eip1967_admin_slot": admin,
        "eip1967_beacon_slot": beacon,
    }
    if impl:
        info.is_proxy, info.kind, info.implementation, info.admin = True, "eip1967", impl, admin
        return info
    if beacon:
        info.is_proxy, info.kind, info.beacon, info.admin = True, "eip1967-beacon", beacon, admin
        out = rpc.try_call(beacon, selector("implementation()"), block)
        if out:
            info.implementation = word_to_address(out)
        else:
            info.unresolved_reason = "Beacon did not return an implementation()."
        return info
    if code.startswith(EIP1167_PREFIX):
        info.is_proxy, info.kind = True, "eip1167"
        info.implementation = validate_address("0x" + code[10:30].hex())
        return info
    legacy = _slot_address(rpc, address, OZ_LEGACY_IMPLEMENTATION_SLOT, block)
    if legacy:
        info.is_proxy, info.kind, info.implementation = True, "oz-legacy", legacy
        info.evidence["oz_legacy_implementation_slot"] = legacy
        return info
    facts = analyze_bytecode(code)
    if facts.has_delegatecall and selector("implementation()") in facts.selectors:
        out = rpc.try_call(address, selector("implementation()"), block)
        if out:
            info.is_proxy, info.kind, info.implementation = True, "eip897", word_to_address(out)
        else:
            info.is_proxy, info.kind = True, "eip897"
            info.unresolved_reason = "implementation() reverted or returned nothing."
    return info


def _resolve_source(chain: ChainConfig, address: str, code: bytes) -> SourceResult:
    if chain.is_local:
        return LocalArtifactProvider().resolve(code)
    return EtherscanProvider(chain.chain_id).resolve(address, code)


def resolve_contract(rpc: RpcClient, chain: ChainConfig, address: str, block: int | None = None) -> ResolvedContract:
    address = validate_address(address, field="hook_address")
    reported = rpc.chain_id()
    if reported != chain.chain_id:
        raise AppError(
            "rpc_chain_mismatch",
            f"The configured RPC endpoint reports chain {reported}, expected {chain.chain_id}.",
            status_code=502,
        )
    latest = rpc.block_number()
    if block is None:
        block = latest
    if block < 0 or block > latest:
        raise AppError("invalid_block", f"Block {block} is outside the chain range 0..{latest}.", status_code=422)
    blk = rpc.get_block(block)
    if not blk:
        raise AppError("block_not_found", f"Block {block} was not found by the RPC endpoint.", status_code=422)
    code_hex = rpc.get_code(address, block)
    code = hex_to_bytes(code_hex)
    if not code:
        nonce = int(rpc.call("eth_getTransactionCount", [address, hex(block)]) or "0x0", 16)
        if nonce > 0:
            raise AppError(
                "address_is_eoa",
                f"{address} is an externally owned account (it has sent transactions), not a hook contract.",
                status_code=422,
            )
        raise AppError("no_contract_code", f"No contract code exists at {address} at block {block}.", status_code=422)

    notes: list[str] = []
    proxy = detect_proxy(rpc, address, code, block)
    impl_code: bytes | None = None
    impl_hash: str | None = None
    proxy_source: SourceResult | None = None
    if proxy.is_proxy and proxy.implementation:
        impl_code = hex_to_bytes(rpc.get_code(proxy.implementation, block))
        if impl_code:
            impl_hash = code_hash(impl_code)
        else:
            proxy.unresolved_reason = "The implementation address has no code at this block."
            impl_code = None

    if proxy.is_proxy:
        proxy_source = _resolve_source(chain, address, code)
        if impl_code:
            source = _resolve_source(chain, proxy.implementation or address, impl_code)
        else:
            source = SourceResult(status="unverified", notes=["Proxy implementation could not be resolved."])
    else:
        source = _resolve_source(chain, address, code)

    status = source.status
    if proxy.is_proxy and not impl_code:
        status = "proxy-unresolved"
    elif status in ("unverified", "unavailable"):
        status = "bytecode-only"
        notes.extend(source.notes)
    return ResolvedContract(
        chain_id=chain.chain_id,
        address=address,
        block_number=block,
        block_hash=str(blk.get("hash")),
        block_timestamp=int(str(blk.get("timestamp", "0x0")), 16),
        runtime_code=code,
        runtime_code_hash=code_hash(code),
        proxy=proxy,
        implementation_code=impl_code,
        implementation_code_hash=impl_hash,
        source=source,
        proxy_source=proxy_source,
        source_status=status,
        notes=notes,
    )
