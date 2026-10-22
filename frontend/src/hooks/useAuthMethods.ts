import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { getAuthMethods } from "../api/client";
import type { AuthMethods } from "../types/auth";

export type AuthMethodsState =
  | { status: "loading" }
  | { status: "ready"; methods: AuthMethods }
  | { status: "failed" };

/** The server's sign-in methods (KTD12), fetched once on mount, for the
 * login and register pages and Settings. While pending the page keeps its controls
 * disabled; on failure it falls back to the password form as it was before
 * providers existed, and offers `retry`. */
export function useAuthMethods(): AuthMethodsState & { retry: () => void } {
  const [state, setState] = useState<AuthMethodsState>({ status: "loading" });
  const mounted = useRef(true);

  const load = useCallback(() => {
    setState({ status: "loading" });
    getAuthMethods()
      .then((methods) => {
        if (mounted.current) setState({ status: "ready", methods });
      })
      .catch(() => {
        if (mounted.current) setState({ status: "failed" });
      });
  }, []);

  useEffect(() => {
    mounted.current = true;
    load();
    return () => {
      mounted.current = false;
    };
  }, [load]);

  return { ...state, retry: load };
}

/** Reads the named query parameters once, on first render, and then removes
 * them from the URL with a `replace` navigation -- for the provider
 * callback's `oidc_error` (and the register page's `username`), so a reload
 * or a shared link doesn't show a stale error again. Pass a module-level
 * constant array. */
export function useOneShotSearchParams<Name extends string>(
  names: readonly Name[],
): Record<Name, string | null> {
  const [searchParams, setSearchParams] = useSearchParams();
  const [values] = useState(
    () =>
      Object.fromEntries(names.map((name) => [name, searchParams.get(name)])) as Record<
        Name,
        string | null
      >,
  );

  useEffect(() => {
    if (!names.some((name) => searchParams.has(name))) return;
    setSearchParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        for (const name of names) next.delete(name);
        return next;
      },
      { replace: true },
    );
  }, [names, searchParams, setSearchParams]);

  return values;
}
