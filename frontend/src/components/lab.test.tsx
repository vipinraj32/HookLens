import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ScenarioRun, Step } from "@/lib/api/models";

import { InvariantPanel } from "./lab";

function step(name: string, metrics?: Record<string, string | boolean>): Step {
  return {
    name,
    phase: "baseline",
    condition: "baseline",
    lp_expectation: "success",
    observed: "success",
    expectation_met: true,
    privileged: false,
    step_status: "passed",
    ...(metrics ? { metrics } : {}),
  } as Step;
}

function run(steps: Step[]): ScenarioRun {
  return {
    id: "r",
    scenario_id: "x",
    status: "passed",
    status_reason: "",
    parameters: {},
    repro_command: "",
    forge_status: null,
    result_meta: {},
    steps,
    trace: {},
  } as ScenarioRun;
}

describe("InvariantPanel", () => {
  it("ignores steps whose metrics are not invariant checks (position liquidity on removals)", () => {
    const { container } = render(
      <InvariantPanel run={run([step("full_remove", { position_liquidity_before: "1000" }), step("add_liquidity")])} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("lists steps that carry invariant checks", () => {
    render(
      <InvariantPanel
        run={run([
          step("exact_in_0_for_1", { actor_delta_matches: true, value_conserved: true, tracked_sum0: "0" }),
          step("full_remove", { position_liquidity_before: "1000" }),
        ])}
      />,
    );
    expect(screen.getByText("Invariants evaluated")).toBeInTheDocument();
    expect(screen.getByText("exact_in_0_for_1")).toBeInTheDocument();
    expect(screen.queryByText("full_remove")).not.toBeInTheDocument();
  });
});
