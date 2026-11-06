"""Verified-source bundle: sources plus solc standard-JSON output (ASTs, ABIs, layouts).

Both providers (Etherscan-verified source compiled locally, and HookLens local forge
artifacts) are normalised into this one structure so analyzers have a single input format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SourceBundle:
    provider: str  # "etherscan" | "local-artifact"
    contract_name: str
    contract_path: str
    compiler_version: str | None
    sources: dict[str, str]  # path -> content
    output_sources: dict[str, dict[str, Any]]  # path -> {"id": int, "ast": {...}}
    output_contracts: dict[str, dict[str, Any]]  # path -> name -> {abi, storageLayout, evm...}
    settings: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def file_by_index(self) -> dict[int, str]:
        return {int(v["id"]): k for k, v in self.output_sources.items() if "id" in v}

    def contract_output(self) -> dict[str, Any]:
        return self.output_contracts.get(self.contract_path, {}).get(self.contract_name, {})

    def abi(self) -> list[Any]:
        return list(self.contract_output().get("abi") or [])

    def storage_layout(self) -> dict[str, Any] | None:
        lay = self.contract_output().get("storageLayout")
        return lay if isinstance(lay, dict) else None

    def summary(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "contract_name": self.contract_name,
            "contract_path": self.contract_path,
            "compiler_version": self.compiler_version,
            "file_count": len(self.sources),
            "files": sorted(self.sources),
            "notes": self.notes,
        }
