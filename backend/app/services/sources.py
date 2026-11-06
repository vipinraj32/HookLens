"""Verified-source providers.

* EtherscanProvider: fetches verified source + compiler settings via the Etherscan v2 API,
  recompiles locally with the exact solc version to obtain the AST, ABI and storage layout,
  and compares the compiled runtime bytecode with the deployed code.
* LocalArtifactProvider: for the local fixture chain, matches deployed runtime code against
  HookLens forge artifacts (immutables masked) and loads the corresponding build-info.

Neither provider ever fabricates source: when nothing matches, the result says so.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from app.config import get_settings
from app.errors import AppError, ExplorerError
from app.services.evm import hex_to_bytes
from hooklens.analyzers.bytecode import mask_immutables, split_metadata
from hooklens.analyzers.source.bundle import SourceBundle

log = logging.getLogger(__name__)


@dataclass
class SourceResult:
    status: str  # verified | partial | unverified | local-artifact | unavailable
    bundle: SourceBundle | None = None
    abi: list[Any] | None = None
    contract_name: str | None = None
    compiler_version: str | None = None
    explorer_proxy_flag: bool | None = None
    explorer_implementation: str | None = None
    bytecode_match: str = "not-checked"  # exact | exact-excluding-metadata | mismatch | not-checked
    notes: list[str] = field(default_factory=list)


def compare_runtime(deployed: bytes, compiled_hex: str, immutable_refs: dict[str, Any] | None) -> str:
    try:
        compiled = hex_to_bytes(compiled_hex if compiled_hex.startswith("0x") else "0x" + compiled_hex)
    except ValueError:
        return "not-checked"
    a = mask_immutables(deployed, immutable_refs)
    b = mask_immutables(compiled, immutable_refs)
    if a == b:
        return "exact"
    ab, _ = split_metadata(a)
    bb, _ = split_metadata(b)
    if ab == bb:
        return "exact-excluding-metadata"
    return "mismatch"


# ====================================================================== local artifacts


class LocalArtifactProvider:
    """Matches runtime code against forge artifacts in contracts/out (local chain only)."""

    _lock = threading.Lock()
    _cache: dict[str, Any] = {}

    def __init__(self, out_dir: Path | None = None) -> None:
        self.out_dir = out_dir or (get_settings().contracts_dir / "out")

    def _artifacts(self) -> list[dict[str, Any]]:
        key = f"artifacts:{self.out_dir}"
        stamp = self.out_dir.stat().st_mtime if self.out_dir.exists() else 0
        with self._lock:
            cached = self._cache.get(key)
            if cached and cached[0] == stamp:
                return list(cached[1])
        items: list[dict[str, Any]] = []
        if self.out_dir.exists():
            for p in self.out_dir.glob("*/*.json"):
                if p.parent.name == "build-info":
                    continue
                try:
                    d = json.loads(p.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                target = ((d.get("metadata") or {}).get("settings") or {}).get("compilationTarget") or {}
                if not target:
                    continue
                path, name = next(iter(target.items()))
                if not str(path).startswith("src/"):
                    continue  # only HookLens contract sources, never tests or scripts
                dep = (d.get("deployedBytecode") or {}).get("object", "")
                if not dep or dep == "0x":
                    continue
                items.append(
                    {
                        "path": path,
                        "name": name,
                        "deployed": dep,
                        "immutables": (d.get("deployedBytecode") or {}).get("immutableReferences") or {},
                    }
                )
        with self._lock:
            self._cache[key] = (stamp, items)
        return items

    def match(self, runtime: bytes) -> dict[str, Any] | None:
        for a in self._artifacts():
            m = compare_runtime(runtime, a["deployed"], a["immutables"])
            if m in ("exact", "exact-excluding-metadata"):
                return a | {"match": m}
        return None

    def bundle_for(self, art: dict[str, Any]) -> SourceBundle | None:
        bi_dir = self.out_dir / "build-info"
        if not bi_dir.exists():
            return None
        for f in sorted(bi_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            c = ((d.get("output") or {}).get("contracts") or {}).get(art["path"], {}).get(art["name"])
            if not c:
                continue
            obj = ((c.get("evm") or {}).get("deployedBytecode") or {}).get("object", "")
            if obj.removeprefix("0x") != art["deployed"].removeprefix("0x"):
                continue
            inp = d.get("input") or {}
            sources = {p: s.get("content", "") for p, s in (inp.get("sources") or {}).items()}
            return SourceBundle(
                provider="local-artifact",
                contract_name=art["name"],
                contract_path=art["path"],
                compiler_version=d.get("solcLongVersion"),
                sources=sources,
                output_sources=(d.get("output") or {}).get("sources") or {},
                output_contracts=(d.get("output") or {}).get("contracts") or {},
                settings=inp.get("settings") or {},
                notes=["Source matched against HookLens local forge build artifacts (fixture chain)."],
            )
        return None

    def resolve(self, runtime: bytes) -> SourceResult:
        art = self.match(runtime)
        if not art:
            return SourceResult(
                status="unverified",
                notes=["Runtime code does not match any HookLens local artifact; analysis is bytecode-only."],
            )
        bundle = self.bundle_for(art)
        if bundle is None:
            return SourceResult(
                status="partial",
                contract_name=art["name"],
                bytecode_match=art["match"],
                notes=["Artifact matched but its build-info is missing; run `forge build` in contracts/."],
            )
        return SourceResult(
            status="local-artifact",
            bundle=bundle,
            abi=bundle.abi(),
            contract_name=bundle.contract_name,
            compiler_version=bundle.compiler_version,
            bytecode_match=art["match"],
            notes=bundle.notes,
        )


# ====================================================================== etherscan


class EtherscanProvider:
    def __init__(self, chain_id: int, *, transport: httpx.BaseTransport | None = None) -> None:
        s = get_settings()
        self.chain_id = chain_id
        self.api_key = s.etherscan_api_key.get_secret_value() if s.etherscan_api_key else None
        self.url = s.etherscan_api_url
        self._transport = transport

    def fetch(self, address: str) -> dict[str, Any] | None:
        if not self.api_key:
            return None
        params = {
            "chainid": str(self.chain_id),
            "module": "contract",
            "action": "getsourcecode",
            "address": address,
            "apikey": self.api_key,
        }
        try:
            with httpx.Client(timeout=20.0, transport=self._transport) as c:
                r = c.get(self.url, params=params)
        except httpx.HTTPError as e:
            raise ExplorerError("The source verification service (Etherscan) is unreachable.") from e
        if r.status_code == 429:
            raise ExplorerError("The source verification service is rate limiting requests.")
        if r.status_code >= 400:
            raise ExplorerError(f"The source verification service returned HTTP {r.status_code}.")
        try:
            body = r.json()
        except ValueError as e:
            raise ExplorerError("The source verification service returned invalid JSON.") from e
        result = body.get("result")
        if body.get("status") == "0" and isinstance(result, str):
            low = result.lower()
            if "rate limit" in low:
                raise ExplorerError("The source verification service is rate limiting requests.")
            if "invalid api key" in low:
                raise ExplorerError("The configured Etherscan API key was rejected.", retryable=False)
        if not isinstance(result, list) or not result:
            return None
        return result[0] if isinstance(result[0], dict) else None

    @staticmethod
    def parse_sources(raw: str, contract_name: str) -> tuple[dict[str, str], dict[str, Any] | None]:
        """Etherscan SourceCode is either standard JSON ({{...}}), a sources map, or one file."""
        txt = raw.strip()
        if txt.startswith("{{") and txt.endswith("}}"):
            std = json.loads(txt[1:-1])
            return {p: s.get("content", "") for p, s in std.get("sources", {}).items()}, std.get("settings")
        if txt.startswith("{"):
            try:
                obj = json.loads(txt)
            except json.JSONDecodeError:
                return {f"{contract_name}.sol": raw}, None
            if "sources" in obj:
                return {p: s.get("content", "") for p, s in obj["sources"].items()}, obj.get("settings")
            return {p: (s.get("content", "") if isinstance(s, dict) else str(s)) for p, s in obj.items()}, None
        return {f"{contract_name}.sol": raw}, None

    def resolve(self, address: str, runtime: bytes) -> SourceResult:
        if not self.api_key:
            return SourceResult(
                status="unavailable",
                notes=["HOOKLENS_ETHERSCAN_API_KEY is not configured; verified source cannot be retrieved."],
            )
        info = self.fetch(address)
        if not info or not info.get("SourceCode"):
            return SourceResult(
                status="unverified", notes=["The explorer reports no verified source for this address."]
            )
        name = info.get("ContractName") or "Contract"
        compiler = (info.get("CompilerVersion") or "").removeprefix("v") or None
        abi: list[Any] | None = None
        try:
            abi = json.loads(info.get("ABI") or "null")
        except json.JSONDecodeError:
            abi = None
        res = SourceResult(
            status="verified",
            abi=abi if isinstance(abi, list) else None,
            contract_name=name,
            compiler_version=compiler,
            explorer_proxy_flag=str(info.get("Proxy")) == "1",
            explorer_implementation=info.get("Implementation") or None,
        )
        try:
            sources, settings = self.parse_sources(info["SourceCode"], name)
        except (json.JSONDecodeError, AttributeError):
            res.status = "partial"
            res.notes.append("Verified source could not be parsed; AST analysis is unavailable.")
            return res
        bundle = compile_bundle(sources, settings, info, name, compiler)
        if bundle is None:
            res.status = "partial"
            res.notes.append(
                "Verified source was retrieved but could not be recompiled locally, so AST-based analysis "
                "and source-to-bytecode correspondence are unavailable."
            )
            return res
        out = bundle.contract_output()
        dep = (out.get("evm") or {}).get("deployedBytecode") or {}
        res.bytecode_match = compare_runtime(runtime, dep.get("object", ""), dep.get("immutableReferences"))
        res.bundle = bundle
        if res.bytecode_match == "mismatch":
            res.notes.append("Recompiled runtime bytecode does NOT match the deployed code.")
        return res


def compile_bundle(
    sources: dict[str, str],
    settings: dict[str, Any] | None,
    info: dict[str, Any],
    name: str,
    compiler: str | None,
) -> SourceBundle | None:
    """Recompile verified sources with the exact solc version (py-solc-x)."""
    if not compiler:
        return None
    try:
        import solcx
    except ImportError:
        return None
    version = compiler.split("+")[0]
    s = get_settings()
    try:
        installed = {str(v) for v in solcx.get_installed_solc_versions()}
        if version not in installed:
            if not s.allow_solc_download:
                return None
            solcx.install_solc(version)
    except Exception as e:  # network / unsupported version
        log.warning("solc install failed", extra={"version": version, "err": type(e).__name__})
        return None
    st: dict[str, Any] = dict(settings or {})
    if not settings:
        st["optimizer"] = {"enabled": str(info.get("OptimizationUsed")) == "1", "runs": int(info.get("Runs") or 200)}
        evm = (info.get("EVMVersion") or "").lower()
        if evm and evm != "default":
            st["evmVersion"] = evm
    st["outputSelection"] = {
        "*": {
            "*": [
                "abi",
                "storageLayout",
                "evm.deployedBytecode.object",
                "evm.deployedBytecode.immutableReferences",
                "evm.methodIdentifiers",
                "metadata",
            ],
            "": ["ast"],
        }
    }
    std = {"language": "Solidity", "sources": {p: {"content": c} for p, c in sources.items()}, "settings": st}
    try:
        out = solcx.compile_standard(std, solc_version=version, allow_paths=".")
    except Exception as e:
        log.warning("solc compile failed", extra={"err": type(e).__name__})
        return None
    contracts = out.get("contracts") or {}
    path = next((p for p, cs in contracts.items() if name in cs), None)
    if path is None:
        return None
    return SourceBundle(
        provider="etherscan",
        contract_name=name,
        contract_path=path,
        compiler_version=compiler,
        sources=sources,
        output_sources=out.get("sources") or {},
        output_contracts=contracts,
        settings=st,
        notes=["Verified source from Etherscan, recompiled locally with the exact compiler version."],
    )


def source_unavailable_reason(chain_is_local: bool) -> str:
    if chain_is_local:
        return "No local artifact matched."
    if not get_settings().etherscan_api_key:
        return "Etherscan API key not configured."
    return "Source not verified on the explorer."


__all__ = ["AppError", "EtherscanProvider", "LocalArtifactProvider", "SourceResult", "compare_runtime"]
