"use client";

import { useCallback, useSyncExternalStore } from "react";

/**
 * The user's preferred network, persisted per browser. `null` means "all networks".
 * It only filters lists and pre-selects the scanner's chain; it never changes which RPC the
 * server uses (RPC endpoints come from server configuration only).
 */
const KEY = "hooklens.network";
const EVENT = "hooklens:network";
let memory: number | null = null;

function read(): number | null {
  try {
    const v = window.localStorage.getItem(KEY);
    return v !== null && /^\d+$/.test(v) ? Number(v) : null;
  } catch {
    return memory;
  }
}

function subscribe(cb: () => void) {
  const onStorage = (e: StorageEvent) => {
    if (e.key === KEY) cb();
  };
  window.addEventListener("storage", onStorage);
  window.addEventListener(EVENT, cb);
  return () => {
    window.removeEventListener("storage", onStorage);
    window.removeEventListener(EVENT, cb);
  };
}

export function useNetwork(): [number | null, (chainId: number | null) => void] {
  const value = useSyncExternalStore(subscribe, read, () => null);
  const set = useCallback((chainId: number | null) => {
    memory = chainId;
    try {
      if (chainId === null) window.localStorage.removeItem(KEY);
      else window.localStorage.setItem(KEY, String(chainId));
    } catch {
      // Storage can be unavailable (private mode); the selection then lasts for this page only.
    }
    window.dispatchEvent(new Event(EVENT));
  }, []);
  return [value, set];
}
