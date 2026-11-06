/**
 * Typed fetch client for the HookLens API.
 *
 * - Same-origin by default (`/api/v1/...` is rewritten to the backend by next.config.ts),
 *   so the anonymous workspace cookie is first-party.
 * - Every response is validated with Zod; a shape mismatch becomes `invalid_response`.
 * - RFC 7807 problem+json errors are normalised into `ApiError`.
 * - Per-request timeout via AbortController, composed with the caller's signal.
 * - Only idempotent GETs are retried, and only for network errors, 429 and 5xx.
 */
import type { z } from "zod";

export const API_BASE = (process.env.NEXT_PUBLIC_HOOKLENS_API_BASE ?? "/api").replace(/\/$/, "");

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: string;
  readonly correlationId: string | null;
  readonly extra: Record<string, unknown>;

  constructor(opts: {
    status: number;
    code: string;
    title?: string;
    detail: string;
    correlationId?: string | null;
    extra?: Record<string, unknown>;
  }) {
    super(opts.title ? `${opts.title}: ${opts.detail}` : opts.detail);
    this.name = "ApiError";
    this.status = opts.status;
    this.code = opts.code;
    this.detail = opts.detail;
    this.correlationId = opts.correlationId ?? null;
    this.extra = opts.extra ?? {};
  }

  get retryable(): boolean {
    return this.status === 0 || this.status === 408 || this.status === 429 || this.status >= 500;
  }
}

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError;
}

type Method = "GET" | "POST";

export interface RequestOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
  retries?: number;
  query?: Record<string, string | number | boolean | null | undefined | string[]>;
}

export function apiUrl(path: string, query?: RequestOptions["query"]): string {
  const url = `${API_BASE}/v1${path}`;
  if (!query) return url;
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => qs.append(k, x));
    else qs.set(k, String(v));
  }
  const s = qs.toString();
  return s ? `${url}?${s}` : url;
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(t);
        reject(signal.reason);
      },
      { once: true },
    );
  });
}

async function toApiError(res: Response): Promise<ApiError> {
  const correlationId = res.headers.get("X-Correlation-ID");
  let body: Record<string, unknown> = {};
  try {
    body = (await res.json()) as Record<string, unknown>;
  } catch {
    /* non-JSON error body */
  }
  const { code, title, detail, ...extra } = body as { code?: string; title?: string; detail?: unknown };
  return new ApiError({
    status: res.status,
    code: typeof code === "string" ? code : `http_${res.status}`,
    title: typeof title === "string" ? title : undefined,
    detail:
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? "The request was rejected by validation."
          : res.statusText || "Request failed",
    correlationId,
    extra,
  });
}

async function request<S extends z.ZodType>(
  method: Method,
  path: string,
  schema: S,
  body: unknown,
  opts: RequestOptions = {},
): Promise<z.infer<S>> {
  const { signal, timeoutMs = 20_000, query } = opts;
  const retries = method === "GET" ? (opts.retries ?? 2) : 0;
  const url = apiUrl(path, query);

  for (let attempt = 0; ; attempt++) {
    const timeout = AbortSignal.timeout(timeoutMs);
    const combined = signal ? AbortSignal.any([signal, timeout]) : timeout;
    let res: Response;
    try {
      res = await fetch(url, {
        method,
        credentials: "include",
        headers: body === undefined ? { Accept: "application/json" } : { "Content-Type": "application/json", Accept: "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: combined,
        cache: "no-store",
      });
    } catch (e) {
      if (signal?.aborted) throw e; // caller cancelled: propagate as-is
      const timedOut = timeout.aborted;
      const err = new ApiError({
        status: timedOut ? 408 : 0,
        code: timedOut ? "timeout" : "network_error",
        detail: timedOut
          ? `The API did not respond within ${Math.round(timeoutMs / 1000)}s.`
          : "Could not reach the HookLens API. Is the backend running?",
      });
      if (attempt < retries) {
        await sleep(400 * 2 ** attempt, signal);
        continue;
      }
      throw err;
    }

    if (!res.ok) {
      const err = await toApiError(res);
      if (err.retryable && attempt < retries) {
        const ra = Number(res.headers.get("Retry-After"));
        await sleep(Number.isFinite(ra) && ra > 0 ? Math.min(ra, 10) * 1000 : 400 * 2 ** attempt, signal);
        continue;
      }
      throw err;
    }

    const json: unknown = res.status === 204 ? null : await res.json();
    const parsed = schema.safeParse(json);
    if (!parsed.success) {
      throw new ApiError({
        status: res.status,
        code: "invalid_response",
        detail: `Unexpected response shape from ${path}: ${parsed.error.issues
          .slice(0, 3)
          .map((i) => `${i.path.join(".") || "(root)"} ${i.message}`)
          .join("; ")}`,
        correlationId: res.headers.get("X-Correlation-ID"),
      });
    }
    return parsed.data;
  }
}

export const api = {
  get: <S extends z.ZodType>(path: string, schema: S, opts?: RequestOptions) =>
    request("GET", path, schema, undefined, opts),
  post: <S extends z.ZodType>(path: string, schema: S, body?: unknown, opts?: RequestOptions) =>
    request("POST", path, schema, body ?? {}, opts),
};

/** Human-readable message for any thrown value. */
export function errorMessage(e: unknown): string {
  if (isApiError(e)) return e.detail;
  if (e instanceof Error) return e.message;
  return "Something went wrong.";
}
