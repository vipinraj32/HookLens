import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api/client";
import type { JobStream } from "@/lib/api/jobs";

import { JobProgress } from "./job-progress";
import { RevertMessage } from "./trace";
import { ErrorState, ProgressBar, SeverityBadge, StatusBadge } from "./ui";

function wrap(ui: ReactNode) {
  return render(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>);
}

describe("states", () => {
  it("shows problem details and correlation id for API errors", () => {
    render(<ErrorState error={new ApiError({ status: 503, code: "rpc_not_configured", detail: "No RPC.", correlationId: "abc" })} />);
    expect(screen.getByRole("alert")).toHaveTextContent("No RPC.");
    expect(screen.getByRole("alert")).toHaveTextContent("code=rpc_not_configured");
    expect(screen.getByRole("alert")).toHaveTextContent("correlation=abc");
  });

  it("labels severity and status in text, never colour alone", () => {
    render(
      <>
        <SeverityBadge severity="high" />
        <StatusBadge status="unexpected_revert" />
      </>,
    );
    expect(screen.getByText("high")).toBeInTheDocument();
    expect(screen.getByText("unexpected revert")).toBeInTheDocument();
  });

  it("exposes progress accessibly", () => {
    render(<ProgressBar value={0.42} label="Scan progress" />);
    expect(screen.getByRole("progressbar", { name: "Scan progress" })).toHaveAttribute("aria-valuenow", "42");
  });
});

describe("JobProgress", () => {
  const base: JobStream = {
    events: [{ ts: "2026-11-06T07:21:43Z", stage: "pools", progress: 0.4, message: "Searching Initialize events", level: "info" }],
    status: "running",
    progress: 0.4,
    stage: "pools",
    error: null,
    transport: "sse",
    done: false,
  };

  it("renders live events and offers cancel while running", () => {
    wrap(<JobProgress jobId="j1" stream={base} title="Scan" />);
    expect(screen.getByText("Searching Initialize events")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Cancel/ })).toBeEnabled();
    expect(screen.getByText(/via SSE/)).toBeInTheDocument();
  });

  it("shows the failure reason when the job ends badly and hides cancel", () => {
    wrap(
      <JobProgress
        jobId="j1"
        stream={{ ...base, done: true, status: "timed_out", transport: "polling", error: { code: "timeout", message: "Job exceeded 600s" } }}
        title="Scan"
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Job exceeded 600s");
    expect(screen.queryByRole("button", { name: /Cancel/ })).not.toBeInTheDocument();
    expect(screen.getByText(/via polling/)).toBeInTheDocument();
  });
});

describe("RevertMessage", () => {
  it("unwraps a v4 WrappedError chain", () => {
    render(
      <RevertMessage
        revert={{
          kind: "wrapped",
          name: "WrappedError",
          function: "beforeRemoveLiquidity(address)",
          message: "Hook call beforeRemoveLiquidity reverted: InvalidOraclePrice(answer=0)",
          inner: { kind: "custom", name: "InvalidOraclePrice", signature: "InvalidOraclePrice(int256)", args: { answer: 0 } },
          details: { kind: "custom", name: "HookCallFailed", signature: "HookCallFailed()" },
        }}
      />,
    );
    expect(screen.getByText(/InvalidOraclePrice\(answer=0\)/)).toBeInTheDocument();
    expect(screen.getByText("InvalidOraclePrice(int256)")).toBeInTheDocument();
    expect(screen.getByText("HookCallFailed()")).toBeInTheDocument();
  });
});
