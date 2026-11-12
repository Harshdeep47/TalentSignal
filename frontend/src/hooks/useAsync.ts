import { useCallback, useEffect, useRef, useState } from "react";

/** Load data with explicit loading / error states; `reload()` re-runs the loader. */
export function useAsync<T>(loader: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const seq = useRef(0);

  const run = useCallback(() => {
    const my = ++seq.current;
    setLoading(true);
    setError(null);
    loader()
      .then((d) => my === seq.current && setData(d))
      .catch((e: Error) => my === seq.current && setError(e.message))
      .finally(() => my === seq.current && setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    run();
  }, [run]);

  return { data, error, loading, reload: run, setData };
}

/** Poll `fn` every `ms` while `active` is true (used for job progress). */
export function usePoll(fn: () => void, ms: number, active: boolean) {
  const saved = useRef(fn);
  saved.current = fn;
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => saved.current(), ms);
    return () => clearInterval(t);
  }, [ms, active]);
}

/** Debounce a fast-changing value (search boxes). */
export function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}
