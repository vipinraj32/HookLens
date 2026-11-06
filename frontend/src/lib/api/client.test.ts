import { afterEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";

import { ApiError, api, apiUrl, errorMessage } from "./client";

function json(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), {
    status: 200,
    ...init,
    headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
  });
}

afterEach(() => vi.restoreAllMocks());

describe("apiUrl", () => {
  it("builds same-origin URLs and drops empty query values", () => {
    expect(apiUrl("/scans", { limit: 5, q: "", x: undefined, ids: ["a", "b"] })).toBe("/api/v1/scans?limit=5&ids=a&ids=b");
    expect(apiUrl("/health")).toBe("/api/v1/health");
  });
});

describe("api client", () => {
  it("validates responses with the schema", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ status: "ok" }));
    await expect(api.get("/health", z.object({ status: z.string() }))).resolves.toEqual({ status: "ok" });
  });

  it("turns a shape mismatch into invalid_response instead of passing bad data on", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ status: 1 }));
    const err = await api.get("/health", z.object({ status: z.string() })).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).code).toBe("invalid_response");
    expect((err as ApiError).detail).toContain("status");
  });

  it("normalises RFC 7807 problem+json errors and does not retry 4xx", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      json(
        { type: "about:blank", title: "Unsupported chain", detail: "Chain 5 is not supported.", code: "unsupported_chain" },
        { status: 422, headers: { "X-Correlation-ID": "cid-1", "Content-Type": "application/problem+json" } },
      ),
    );
    const err = (await api.get("/scans", z.unknown()).catch((e: unknown) => e)) as ApiError;
    expect(err.status).toBe(422);
    expect(err.code).toBe("unsupported_chain");
    expect(err.correlationId).toBe("cid-1");
    expect(errorMessage(err)).toBe("Chain 5 is not supported.");
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("retries GETs on 5xx then succeeds", async () => {
    const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json({ code: "boom", detail: "x" }, { status: 503 }))
      .mockResolvedValueOnce(json({ ok: true }));
    await expect(api.get("/x", z.object({ ok: z.boolean() }), { retries: 1 })).resolves.toEqual({ ok: true });
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("never retries POSTs, which may not be idempotent", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ code: "boom", detail: "x" }, { status: 503 }));
    await expect(api.post("/scans", z.unknown(), {})).rejects.toBeInstanceOf(ApiError);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("reports network failures with a helpful message", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    const err = (await api.get("/x", z.unknown(), { retries: 0 }).catch((e: unknown) => e)) as ApiError;
    expect(err.code).toBe("network_error");
    expect(err.retryable).toBe(true);
  });

  it("times out slow requests", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(
      (_url, init) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
        }),
    );
    const err = (await api.get("/slow", z.unknown(), { retries: 0, timeoutMs: 20 }).catch((e: unknown) => e)) as ApiError;
    expect(err.code).toBe("timeout");
    expect(err.status).toBe(408);
  });

  it("propagates caller cancellation untouched", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(
      (_url, init) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
        }),
    );
    const ctl = new AbortController();
    const p = api.get("/x", z.unknown(), { signal: ctl.signal });
    ctl.abort();
    await expect(p).rejects.toMatchObject({ name: "AbortError" });
  });
});
