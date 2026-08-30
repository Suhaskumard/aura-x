import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, listRepositories } from '../api'
import type { RepositorySummary } from '../api'
import StatusBadge from './StatusBadge'

interface Props {
  onSelect: (repositoryId: string) => void
  refreshToken: number
}

// Kept at the previous value so no repository that used to be visible is now
// hidden -- pages 2+ simply make the rest reachable. Matches the backend's
// `page_size` cap of 100 (GET /api/v1/repositories).
const PAGE_SIZE = 50

interface PageData {
  items: RepositorySummary[]
  total: number
}

export default function RepositoryList({ onSelect, refreshToken }: Props) {
  const [data, setData] = useState<PageData | null>(null)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Monotonic id for the most recent page request. A slower earlier response
  // (rapid Next/Previous, or an in-flight request superseded by a refresh) must
  // never overwrite a newer page -- every resolution checks it is still newest.
  const requestSeqRef = useRef(0)
  // The page we have most recently *decided* to show. Updated synchronously in
  // `goToPage` (before React commits `setPage`), so a click whose handler still
  // closes over the previous render's `page` cannot fire a duplicate request
  // for a page that is already loading or already shown.
  const targetPageRef = useRef(1)
  // Synchronous mirror of `loading` for the same reason (state is batched).
  const loadingRef = useRef(false)

  const fetchPage = useCallback(async (target: number) => {
    const seq = (requestSeqRef.current += 1)
    targetPageRef.current = target
    loadingRef.current = true
    setLoading(true)
    setError(null)
    try {
      const result = await listRepositories(target, PAGE_SIZE)
      if (seq !== requestSeqRef.current) return
      setData({ items: result.items, total: result.total })
      setPage(target)
    } catch (err: unknown) {
      if (seq !== requestSeqRef.current) return
      // Roll the intent back to the page that is actually on screen so the
      // current page is not corrupted and the same control retries cleanly.
      targetPageRef.current = page
      setError(err instanceof ApiError ? err.message : 'Could not load repositories.')
    } finally {
      if (seq === requestSeqRef.current) {
        loadingRef.current = false
        setLoading(false)
      }
    }
  }, [page])

  useEffect(() => {
    // A refresh (onboarding started, or "Back to repositories") returns to the
    // first page -- the newest repositories sort there.
    targetPageRef.current = 1
    void fetchPage(1)
    return () => {
      // invalidate any in-flight request on unmount / refresh
      requestSeqRef.current += 1
    }
    // fetchPage depends on `page` but the effect must only re-run on refresh
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshToken])

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1
  const canPrev = !loading && page > 1
  const canNext = !loading && page < totalPages

  const goToPage = (target: number) => {
    // Guards are all synchronous (refs, not batched state): never below page 1,
    // never re-request the page we're already showing or already loading.
    if (loadingRef.current || target < 1 || target === targetPageRef.current) return
    void fetchPage(target)
  }

  // ---- initial load / hard failure ------------------------------------------
  if (!data) {
    if (error) return <p className="error-text">{error}</p>
    return <p className="muted">Loading repositories…</p>
  }

  const showPager = totalPages > 1 || page > 1
  const emptyPage = data.items.length === 0

  return (
    <div className="repository-list">
      {error && <p className="error-text">{error}</p>}

      {emptyPage ? (
        page === 1 ? (
          <p className="muted">No repositories analyzed yet -- paste a URL below to start.</p>
        ) : (
          <p className="muted">No repositories on this page.</p>
        )
      ) : (
        <ul className="repository-cards" aria-busy={loading || undefined}>
          {data.items.map((repo) => (
            <li key={repo.id}>
              <button type="button" className="repository-card" onClick={() => onSelect(repo.id)}>
                <div className="repository-card-title">
                  <span>
                    {repo.owner}/{repo.name}
                  </span>
                  <StatusBadge status={repo.latest_status} />
                </div>
                {repo.description && <p className="muted">{repo.description}</p>}
                <div className="repository-card-meta">
                  {repo.primary_language && <span>{repo.primary_language}</span>}
                  <span>★ {repo.stargazers_count}</span>
                  <span>⑂ {repo.forks_count}</span>
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}

      {showPager && (
        <nav className="pagination" aria-label="Repository list pages">
          <button
            type="button"
            className="pagination-button"
            onClick={() => goToPage(page - 1)}
            disabled={!canPrev}
            aria-label="Previous page"
          >
            ← Previous
          </button>
          <span className="pagination-status" aria-live="polite">
            {loading ? 'Loading…' : `Page ${page} of ${totalPages}`}
          </span>
          <button
            type="button"
            className="pagination-button"
            onClick={() => goToPage(page + 1)}
            disabled={!canNext}
            aria-label="Next page"
          >
            Next →
          </button>
        </nav>
      )}
    </div>
  )
}
