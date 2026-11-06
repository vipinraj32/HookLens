"""Deterministic validation of AI explanations against the evidence they were given.

An explanation is rejected when it cites evidence that was not provided, cites source lines
outside the cited evidence, cites simulation steps that did not run, introduces numbers absent
from the deterministic outputs, restates the finding at a different severity, or makes
exploitability / safety-guarantee claims.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.ai.schemas import LpExplanation, TechnicalExplanation

_NUMBER = re.compile(r"(?<![A-Za-z0-9_])(?:0x[0-9a-fA-F]+|\d[\d,_]*(?:\.\d+)?)(?![A-Za-z0-9_])")
_SEVERITY = re.compile(r"\b(critical|high|medium|low|informational)[- ](?:severity|risk)\b", re.I)
_BANNED = [
    re.compile(p, re.I)
    for p in (
        r"\bexploit(?:able|ed|ing)?\b",
        r"\battacker(?:s)? (?:can|could|will) (?:steal|drain)",
        r"\bdrain(?:s|ed|ing)? (?:the )?(?:pool|funds|liquidity)",
        r"\b(?:is|are) (?:completely |fully )?safe\b",
        r"\bguarantee[sd]?\b",
        r"\brisk[- ]free\b",
        r"\bno risk\b",
        r"\b(?:has been|was) audited\b",
        r"\brug ?pull\b",
    )
]
SMALL_NUMBER_LIMIT = 10


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    checks: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "errors": self.errors, "checks": self.checks}


def _norm(n: str) -> str:
    return n.replace(",", "").replace("_", "").lower()


def _numbers(text: str) -> set[str]:
    return {_norm(m.group(0)) for m in _NUMBER.finditer(text)}


def validate(tech: TechnicalExplanation, lp: LpExplanation, context: dict[str, Any]) -> ValidationResult:
    errors: list[str] = []
    evidence: dict[str, dict[str, Any]] = context["evidence"]
    steps: set[tuple[str, str]] = {(s["scenario"], s["step"]) for s in context.get("simulation_steps", [])}
    severity = context["finding"]["severity"]

    cited = set(tech.evidence_refs) | set(lp.evidence_refs)
    unknown = sorted(cited - set(evidence))
    if unknown:
        errors.append(f"Cites evidence that was not provided: {unknown}")
    if not cited:
        errors.append("Cites no evidence.")

    for ref in tech.source_refs:
        ok = any(
            e.get("source_file") == ref.file
            and e.get("line_start") is not None
            and e["line_start"] <= ref.line_start <= ref.line_end <= (e.get("line_end") or e["line_start"])
            for e in evidence.values()
        )
        if not ok:
            errors.append(
                f"Source reference {ref.file}:{ref.line_start}-{ref.line_end} is outside the provided evidence."
            )

    for sref in tech.simulation_refs:
        if (sref.scenario, sref.step) not in steps:
            errors.append(f"Simulation reference {sref.scenario}/{sref.step} did not run in the provided results.")

    text = " ".join([tech.summary, tech.mechanism, lp.what_it_means, lp.when_it_matters, *lp.what_to_check])
    allowed = _numbers(context["facts_text"])
    allowed |= {str(r.line_start) for r in tech.source_refs} | {str(r.line_end) for r in tech.source_refs}
    novel = sorted(
        n
        for n in _numbers(text)
        if n not in allowed
        and not (n.isdigit() and int(n) <= SMALL_NUMBER_LIMIT)
        and not any(n in a for a in allowed if len(n) >= 3)
    )
    if novel:
        errors.append(f"Introduces numbers not present in the deterministic outputs: {novel[:10]}")

    for m in _SEVERITY.finditer(text):
        if m.group(1).lower() != severity:
            errors.append(
                f"Restates severity as '{m.group(1).lower()}' but the deterministic severity is '{severity}'."
            )

    for p in _BANNED:
        hit = p.search(text)
        if hit:
            errors.append(f"Makes an unsupported claim: '{hit.group(0)}'.")

    return ValidationResult(
        not errors,
        errors,
        {
            "evidence_cited": sorted(cited),
            "source_refs": len(tech.source_refs),
            "simulation_refs": len(tech.simulation_refs),
            "numbers_checked": len(_numbers(text)),
        },
    )
