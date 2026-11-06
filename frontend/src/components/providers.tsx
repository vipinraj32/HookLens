"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { isApiError } from "@/lib/api/client";

let browserClient: QueryClient | undefined;

function makeClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        // The fetch client already retries transient GET failures; don't multiply them here,
        // and never retry deterministic 4xx errors.
        retry: (count, err) => count < 1 && (!isApiError(err) || err.retryable),
        refetchOnWindowFocus: false,
      },
      mutations: { retry: false },
    },
  });
}

function getClient() {
  if (typeof window === "undefined") return makeClient();
  browserClient ??= makeClient();
  return browserClient;
}

export function Providers({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={getClient()}>{children}</QueryClientProvider>;
}
