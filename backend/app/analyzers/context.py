"""Analysis context shared by all analyzers, plus evidence helpers."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from eth_utils import to_checksum_address

from app.analyzers.bytecode import BytecodeFacts
from app.analyzers.core import Collector, ConfidenceBasis
from app.analyzers.permissions import Permission
from app.analyzers.source.ast_index import AstIndex, FunctionInfo, Location, StateVar
from app.services.evm import ZERO_ADDRESS, hex_to_bytes

log = logging.getLogger(__name__)

POOL_MANAGER_NAMES = ("poolmanager", "manager")


@dataclass
class AnalysisContext:
    chain_id: int
    address: str
    block_number: int
    pool_manager: str | None
    permissions: list[Permission]
    logic_facts: BytecodeFacts
    proxy_facts: BytecodeFacts | None
    resolved: Any  # ResolvedContract
    index: AstIndex | None
    proxy_index: AstIndex | None
    pools: list[dict[str, Any]] = field(default_factory=list)
    rpc_call: Callable[[str, str], str | None] | None = None
    rpc_storage: Callable[[str, int], str] | None = None
    rpc_code: Callable[[str], str] | None = None
    facts: dict[str, Any] = field(default_factory=dict)  # cross-analyzer facts (simulation plan inputs)

    # ------------------------------------------------------------------ permissions
    def enabled(self, flag: str) -> bool:
        return any(p.flag == flag and p.enabled for p in self.permissions)

    def enabled_callbacks(self) -> list[str]:
        return sorted({p.callback for p in self.permissions if p.enabled})

    def callback_functions(self) -> dict[str, FunctionInfo]:
        if not self.index:
            return {}
        out = {}
        for cb in self.enabled_callbacks():
            fi = self.index.resolve(cb)
            if fi is not None:
                out[cb] = fi
        return out

    # ------------------------------------------------------------------ state values
    def state_var_value(self, sv: StateVar) -> dict[str, Any]:
        """Best-effort read of a state variable's current value at the pinned block.

        Order: public getter (eth_call) -> immutable (from deployed bytecode) -> storage slot via
        the compiler's storage layout. Returns {"value": ..., "method": ...} or {"method": "unavailable"}.
        """
        target = self.address  # proxies: storage lives at the proxy; getters are routed via the proxy
        if sv.constant:
            return {"value": sv.value_text, "method": "constant"}
        if sv.selector and self.rpc_call:
            try:
                out = self.rpc_call(target, sv.selector)
            except Exception:  # RPC failures are reported as unavailable, never fatal
                out = None
            if out:
                return {"value": self._decode_word(out, sv.type_string), "method": "public-getter"}
        if sv.immutable and self.index:
            refs = (
                ((self.index.bundle.contract_output().get("evm") or {}).get("deployedBytecode") or {})
                .get("immutableReferences", {})
                .get(str(sv.id))
            )
            code = self.resolved.logic_code if self.resolved is not None else b""
            if refs and code:
                start = int(refs[0]["start"])
                word = code[start : start + 32]
                return {"value": self._decode_word("0x" + word.hex(), sv.type_string), "method": "immutable-bytecode"}
        layout = self.index.bundle.storage_layout() if self.index else None
        if layout and self.rpc_storage:
            for entry in layout.get("storage", []):
                if int(entry.get("astId", -1)) == sv.id:
                    try:
                        word = self.rpc_storage(target, int(entry["slot"]))
                    except Exception:
                        return {"method": "unavailable"}
                    raw = hex_to_bytes(word).rjust(32, b"\x00")
                    offset = int(entry.get("offset", 0))
                    size = 20 if sv.type_string.startswith(("address", "contract")) else 32 - offset
                    chunk = raw[32 - offset - size : 32 - offset]
                    return {
                        "value": self._decode_word("0x" + chunk.rjust(32, b"\x00").hex(), sv.type_string),
                        "method": "storage-layout",
                        "slot": entry["slot"],
                    }
        return {"method": "unavailable"}

    @staticmethod
    def _decode_word(out: str, type_string: str) -> Any:
        raw = hex_to_bytes(out)[:32].rjust(32, b"\x00")
        if type_string.startswith(("address", "contract")):
            return to_checksum_address("0x" + raw[12:].hex())
        if type_string == "bool":
            return raw[-1] == 1
        if type_string.startswith("uint"):
            return str(int.from_bytes(raw, "big"))
        if type_string.startswith("int"):
            v = int.from_bytes(raw, "big")
            return str(v - (1 << 256) if v >> 255 else v)
        return "0x" + raw.hex()

    def is_contract(self, address: str) -> bool | None:
        if not self.rpc_code or address == ZERO_ADDRESS:
            return None
        try:
            return self.rpc_code(address) not in ("0x", "")
        except Exception:
            return None

    def is_pool_manager_var(self, sv_id: int | None) -> bool:
        if sv_id is None or not self.index:
            return False
        sv = self.index.state_var(sv_id)
        if sv is None:
            node = self.index.nodes.get(sv_id) or {}
            name = str(node.get("name", "")).lower()
            typ = str((node.get("typeDescriptions") or {}).get("typeString", ""))
        else:
            name, typ = sv.name.lower(), sv.type_string
        return "PoolManager" in typ or name in POOL_MANAGER_NAMES

    # ------------------------------------------------------------------ evidence helpers
    def ev_function(self, out: Collector, fi: FunctionInfo, title: str | None = None) -> str:
        assert self.index is not None
        ex = self.index.excerpt(fi.loc)
        return out.evidence_item(
            "source_excerpt",
            f"{fi.loc.file}:{fi.loc.line_start}:{fi.name}",
            title or f"{fi.contract}.{fi.name}",
            ConfidenceBasis.SOURCE_AST,
            {"excerpt": ex, "signature": fi.signature, "modifiers": fi.modifiers, "selector": fi.selector},
            source_file=ex["file"],
            line_start=ex["line_start"],
            line_end=ex["line_end"],
            function_name=fi.name,
        )

    def ev_location(
        self, out: Collector, loc: Location, title: str, fn: str | None = None, extra: dict[str, Any] | None = None
    ) -> str:
        assert self.index is not None
        ex = self.index.excerpt(loc, max_lines=20)
        return out.evidence_item(
            "source_excerpt",
            f"{loc.file}:{loc.line_start}-{loc.line_end}",
            title,
            ConfidenceBasis.SOURCE_AST,
            {"excerpt": ex, **(extra or {})},
            source_file=ex["file"],
            line_start=ex["line_start"],
            line_end=ex["line_end"],
            function_name=fn,
        )

    def ev_state_var(self, out: Collector, sv: StateVar) -> str:
        value = self.state_var_value(sv)
        assert self.index is not None
        ex = self.index.excerpt(sv.loc, max_lines=3)
        basis = (
            ConfidenceBasis.RPC_STATE
            if value.get("method") in ("public-getter", "storage-layout")
            else ConfidenceBasis.SOURCE_AST
        )
        return out.evidence_item(
            "state_variable",
            f"{sv.contract}.{sv.name}@{self.block_number}",
            f"State variable {sv.contract}.{sv.name}",
            basis,
            {
                "name": sv.name,
                "type": sv.type_string,
                "visibility": sv.visibility,
                "constant": sv.constant,
                "immutable": sv.immutable,
                "value_at_block": value,
                "block_number": self.block_number,
                "excerpt": ex,
            },
            source_file=ex["file"],
            line_start=ex["line_start"],
            line_end=ex["line_end"],
        )
