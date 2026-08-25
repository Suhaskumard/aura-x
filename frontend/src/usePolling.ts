import { useEffect, useRef, useState } from 'react'

/**
 * Polls `fetcher` on an interval until `isTerminal(value)` is true.
 * Every value shown to the user comes from a real response -- there is
 * no simulated/fake progress anywhere in this hook (Phase 13's explicit
 * requirement).
 */
export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs: number,
  isTerminal: (value: T) => boolean,
  deps: unknown[],
) {
  const [value, setValue] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | null = null

    async function poll() {
      try {
        const result = await fetcherRef.current()
        if (cancelled) return
        setValue(result)
        setError(null)
        if (!isTerminal(result)) {
          timer = setTimeout(poll, intervalMs)
        }
      } catch (err) {
        if (cancelled) return
        setError(err instanceof Error ? err.message : 'Polling failed')
        timer = setTimeout(poll, intervalMs)
      }
    }

    setValue(null)
    setError(null)
    void poll()

    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
    // deps intentionally drive re-polling from scratch; fetcher/isTerminal
    // identity changes are expected not to (they're recreated per render).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return { value, error }
}
