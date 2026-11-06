"""Structured outputs the model must return. Every claim carries references we can verify."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SourceRef(BaseModel):
    file: str
    line_start: int
    line_end: int


class SimulationRef(BaseModel):
    scenario: str
    step: str


class TechnicalExplanation(BaseModel):
    summary: str = Field(description="Two or three sentences: what the code does, grounded in the evidence.")
    mechanism: str = Field(description="How the behaviour arises, step by step, citing evidence IDs inline.")
    evidence_refs: list[str] = Field(description="Evidence IDs (EV-...) that support the explanation.")
    source_refs: list[SourceRef] = Field(description="Source line ranges cited; must lie inside cited evidence.")
    simulation_refs: list[SimulationRef] = Field(description="Simulation steps cited; empty if none provided.")


class LpExplanation(BaseModel):
    what_it_means: str = Field(description="Plain-language meaning for a liquidity provider.")
    when_it_matters: str = Field(description="Conditions under which it affects an LP position.")
    what_to_check: list[str] = Field(description="Concrete things an LP can verify before providing liquidity.")
    evidence_refs: list[str] = Field(description="Evidence IDs supporting these statements.")


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic JSON schema adjusted for structured outputs: closed objects, all fields required."""
    schema = model.model_json_schema()

    def fix(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"])
            for v in node.values():
                fix(v)
        elif isinstance(node, list):
            for v in node:
                fix(v)

    fix(schema)
    return schema
