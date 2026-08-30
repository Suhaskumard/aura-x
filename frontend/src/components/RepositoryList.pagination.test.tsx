import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api'
import type { PaginatedRepositories, RepositorySummary } from '../api'
import RepositoryList from './RepositoryList'

/**
 * FE-M1: RepositoryList only ever fetched page 1 (`listRepositories(1, 50)`) and
 * ignored `total`/`page`/`page_size`, so a user with more than one page of
 * analysed repositories could never reach the rest. These tests cover the real
 * pagination added on top of the backend's existing `?page=&page_size=` contract.
 */

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api')
  return { ...actual, listRepositories: vi.fn() }
})
import { listRepositories } from '../api'

const PAGE_SIZE = 50

function repo(i: number, over: Partial<RepositorySummary> = {}): RepositorySummary {
  return {
    id: `repo-${i}`,
    provider: 'github',
    owner: 'octocat',
    name: `repo-${i}`,
    source_url: `https://github.com/octocat/repo-${i}`,
    default_branch: 'main',
    description: null,
    visibility: 'public',
    primary_language: null,
    stargazers_count: i,
    forks_count: 0,
    latest_status: 'READY',
    updated_at: '2026-01-01T00:00:00Z',
    ...over,
  }
}

/** a page slice of a synthetic dataset of `total` repos */
function pageOf(total: number, page: number): PaginatedRepositories {
  const start = (page - 1) * PAGE_SIZE
  const items = Array.from({ length: Math.max(0, Math.min(PAGE_SIZE, total - start)) }, (_, k) => repo(start + k + 1))
  return { items, total, page, page_size: PAGE_SIZE }
}

beforeEach(() => vi.mocked(listRepositories).mockReset())

describe('RepositoryList pagination (FE-M1)', () => {
  it('requests page 1 with the real page size on mount', async () => {
    vi.mocked(listRepositories).mockResolvedValue(pageOf(3, 1))
    render(<RepositoryList onSelect={vi.fn()} refreshToken={0} />)
    await screen.findByText('octocat/repo-1')
    expect(listRepositories).toHaveBeenCalledWith(1, PAGE_SIZE)
  })

  it('single-page dataset (< page size) shows no pager at all', async () => {
    vi.mocked(listRepositories).mockResolvedValue(pageOf(10, 1))
    render(<RepositoryList onSelect={vi.fn()} refreshToken={0} />)
    await screen.findByText('octocat/repo-1')
    expect(screen.queryByRole('navigation', { name: /repository list pages/i })).not.toBeInTheDocument()
  })

  it('exact-page-size dataset (== page size) also shows no pager', async () => {
    vi.mocked(listRepositories).mockResolvedValue(pageOf(PAGE_SIZE, 1))
    render(<RepositoryList onSelect={vi.fn()} refreshToken={0} />)
    await screen.findByText('octocat/repo-1')
    expect(screen.queryByRole('navigation', { name: /repository list pages/i })).not.toBeInTheDocument()
  })

  it('one-item dataset renders one card and no pager', async () => {
    vi.mocked(listRepositories).mockResolvedValue(pageOf(1, 1))
    render(<RepositoryList onSelect={vi.fn()} refreshToken={0} />)
    await screen.findByText('octocat/repo-1')
    expect(screen.getAllByRole('listitem')).toHaveLength(1)
    expect(screen.queryByRole('navigation', { name: /repository list pages/i })).not.toBeInTheDocument()
  })

  it('multi-page dataset: shows "Page 1 of N", Previous disabled, Next enabled', async () => {
    vi.mocked(listRepositories).mockResolvedValue(pageOf(120, 1)) // 3 pages
    render(<RepositoryList onSelect={vi.fn()} refreshToken={0} />)
    await screen.findByText('octocat/repo-1')
    expect(screen.getByText('Page 1 of 3')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /previous page/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /next page/i })).toBeEnabled()
  })

  it('Next / Previous move between pages, requesting the right page each time', async () => {
    vi.mocked(listRepositories).mockImplementation((p = 1) => Promise.resolve(pageOf(120, p)))
    const user = userEvent.setup()
    render(<RepositoryList onSelect={vi.fn()} refreshToken={0} />)
    await screen.findByText('octocat/repo-1')

    await user.click(screen.getByRole('button', { name: /next page/i }))
    await screen.findByText('octocat/repo-51')
    expect(screen.getByText('Page 2 of 3')).toBeInTheDocument()
    expect(screen.queryByText('octocat/repo-1')).not.toBeInTheDocument() // no page mixing
    expect(listRepositories).toHaveBeenLastCalledWith(2, PAGE_SIZE)

    await user.click(screen.getByRole('button', { name: /next page/i }))
    await screen.findByText('octocat/repo-101')
    expect(screen.getByText('Page 3 of 3')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /next page/i })).toBeDisabled() // last page

    await user.click(screen.getByRole('button', { name: /previous page/i }))
    await screen.findByText('octocat/repo-51')
    expect(screen.getByText('Page 2 of 3')).toBeInTheDocument()
  })

  it('shows a loading state while changing pages and disables both controls', async () => {
    let resolveSecond: (v: PaginatedRepositories) => void = () => {}
    vi.mocked(listRepositories).mockImplementation((p = 1) =>
      p === 1 ? Promise.resolve(pageOf(120, 1)) : new Promise<PaginatedRepositories>((r) => (resolveSecond = r)),
    )
    const user = userEvent.setup()
    render(<RepositoryList onSelect={vi.fn()} refreshToken={0} />)
    await screen.findByText('octocat/repo-1')

    await user.click(screen.getByRole('button', { name: /next page/i }))
    expect(await screen.findByText('Loading…')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /previous page/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /next page/i })).toBeDisabled()

    resolveSecond(pageOf(120, 2))
    await screen.findByText('Page 2 of 3')
  })

  it('rapid Next clicks do not duplicate requests or let a stale page win', async () => {
    const resolvers: Record<number, (v: PaginatedRepositories) => void> = {}
    vi.mocked(listRepositories).mockImplementation((p = 1) => {
      if (p === 1) return Promise.resolve(pageOf(200, 1)) // 4 pages
      return new Promise<PaginatedRepositories>((r) => (resolvers[p] = r))
    })
    render(<RepositoryList onSelect={vi.fn()} refreshToken={0} />)
    await screen.findByText('octocat/repo-1')

    const next = screen.getByRole('button', { name: /next page/i })
    // three synchronous clicks in one tick -- the synchronous guards (loadingRef
    // + targetPageRef) must collapse them into a single page-2 request.
    fireEvent.click(next)
    fireEvent.click(next)
    fireEvent.click(next)
    await Promise.resolve()

    const requested = vi.mocked(listRepositories).mock.calls.map((c) => c[0])
    expect(requested.filter((p) => p === 2)).toHaveLength(1)
    expect(requested).not.toContain(3)

    // resolve page 2 out of order after a (hypothetical) later page - the guard
    // means whatever is newest wins; here page 2 is the only in-flight request
    resolvers[2]?.(pageOf(200, 2))
    await screen.findByText('Page 2 of 4')
    expect(screen.getByText('octocat/repo-51')).toBeInTheDocument()
    expect(screen.queryByText('octocat/repo-1')).not.toBeInTheDocument()
  })

  it('a stale in-flight page response is dropped when a refresh supersedes it', async () => {
    let resolvePage2: (v: PaginatedRepositories) => void = () => {}
    vi.mocked(listRepositories).mockImplementation((p = 1) =>
      p === 2 ? new Promise<PaginatedRepositories>((r) => (resolvePage2 = r)) : Promise.resolve(pageOf(200, 1)),
    )
    const user = userEvent.setup()
    const { rerender } = render(<RepositoryList onSelect={vi.fn()} refreshToken={0} />)
    await screen.findByText('octocat/repo-1')

    await user.click(screen.getByRole('button', { name: /next page/i })) // page 2, hangs
    await screen.findByText('Loading…')

    // refresh supersedes the in-flight page-2 request
    rerender(<RepositoryList onSelect={vi.fn()} refreshToken={1} />)
    await screen.findByText('Page 1 of 4')

    // the stale page-2 response finally lands - it must not move us off page 1
    resolvePage2({ items: [repo(51)], total: 200, page: 2, page_size: PAGE_SIZE })
    await new Promise((r) => setTimeout(r, 0))
    expect(screen.getByText('Page 1 of 4')).toBeInTheDocument()
    expect(screen.queryByText('octocat/repo-51')).not.toBeInTheDocument()
  })

  it('API failure while changing pages: shows the error, keeps the current page, and retries', async () => {
    let attempt = 0
    vi.mocked(listRepositories).mockImplementation((p = 1) => {
      if (p === 1) return Promise.resolve(pageOf(120, 1))
      attempt += 1
      return attempt === 1
        ? Promise.reject(new ApiError('RATE_LIMITED', 'Slow down', 429))
        : Promise.resolve(pageOf(120, 2))
    })
    const user = userEvent.setup()
    render(<RepositoryList onSelect={vi.fn()} refreshToken={0} />)
    await screen.findByText('octocat/repo-1')

    await user.click(screen.getByRole('button', { name: /next page/i }))
    expect(await screen.findByText('Slow down')).toBeInTheDocument()
    // current page not corrupted - still page 1, still showing page-1 cards
    expect(screen.getByText('Page 1 of 3')).toBeInTheDocument()
    expect(screen.getByText('octocat/repo-1')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /next page/i })).toBeEnabled()

    // retry the same control -> succeeds -> error clears
    await user.click(screen.getByRole('button', { name: /next page/i }))
    await screen.findByText('Page 2 of 3')
    expect(screen.queryByText('Slow down')).not.toBeInTheDocument()
  })

  it('a refresh (refreshToken change) returns to page 1', async () => {
    vi.mocked(listRepositories).mockImplementation((p = 1) => Promise.resolve(pageOf(120, p)))
    const user = userEvent.setup()
    const { rerender } = render(<RepositoryList onSelect={vi.fn()} refreshToken={0} />)
    await screen.findByText('octocat/repo-1')
    await user.click(screen.getByRole('button', { name: /next page/i }))
    await screen.findByText('Page 2 of 3')

    rerender(<RepositoryList onSelect={vi.fn()} refreshToken={1} />)
    await waitFor(() => expect(screen.getByText('Page 1 of 3')).toBeInTheDocument())
    expect(screen.getByText('octocat/repo-1')).toBeInTheDocument()
    expect(vi.mocked(listRepositories).mock.calls.at(-1)?.[0]).toBe(1)
  })

  it('an empty non-first page (dataset shrank) shows a message and Previous still works', async () => {
    vi.mocked(listRepositories).mockImplementation((p = 1) => {
      if (p === 1) return Promise.resolve(pageOf(120, 1))
      // page 2 requested but the dataset is now empty beyond page 1
      return Promise.resolve({ items: [], total: 50, page: p, page_size: PAGE_SIZE })
    })
    const user = userEvent.setup()
    render(<RepositoryList onSelect={vi.fn()} refreshToken={0} />)
    await screen.findByText('octocat/repo-1')
    await user.click(screen.getByRole('button', { name: /next page/i }))
    expect(await screen.findByText('No repositories on this page.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /previous page/i })).toBeEnabled()
  })
})
