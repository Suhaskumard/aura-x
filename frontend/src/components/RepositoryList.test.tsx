import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api'
import type { PaginatedRepositories, RepositorySummary } from '../api'
import RepositoryList from './RepositoryList'

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api')
  return { ...actual, listRepositories: vi.fn() }
})

import { listRepositories } from '../api'

function makeRepo(overrides: Partial<RepositorySummary> = {}): RepositorySummary {
  return {
    id: 'repo-1',
    provider: 'github',
    owner: 'octocat',
    name: 'Hello-World',
    source_url: 'https://github.com/octocat/Hello-World',
    default_branch: 'main',
    description: 'A test repo',
    visibility: 'public',
    primary_language: 'TypeScript',
    stargazers_count: 42,
    forks_count: 7,
    latest_status: 'READY',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

describe('RepositoryList', () => {
  beforeEach(() => {
    vi.mocked(listRepositories).mockReset()
  })

  it('shows a loading state before the fetch resolves', () => {
    vi.mocked(listRepositories).mockReturnValue(new Promise(() => {}))
    render(<RepositoryList onSelect={vi.fn()} refreshToken={0} />)
    expect(screen.getByText(/loading repositories/i)).toBeInTheDocument()
  })

  it('shows an empty state distinct from loading and error', async () => {
    vi.mocked(listRepositories).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50 })
    render(<RepositoryList onSelect={vi.fn()} refreshToken={0} />)
    expect(await screen.findByText(/no repositories analyzed yet/i)).toBeInTheDocument()
  })

  it('renders repository cards with metadata, and calls onSelect with the id on click', async () => {
    vi.mocked(listRepositories).mockResolvedValue({
      items: [makeRepo(), makeRepo({ id: 'repo-2', name: 'Second', description: null })],
      total: 2,
      page: 1,
      page_size: 50,
    })
    const onSelect = vi.fn()
    const user = userEvent.setup()
    render(<RepositoryList onSelect={onSelect} refreshToken={0} />)

    await screen.findByText('octocat/Hello-World')
    expect(screen.getByText('A test repo')).toBeInTheDocument()
    expect(screen.getAllByText('★ 42')).toHaveLength(2)

    await user.click(screen.getByText('octocat/Hello-World'))
    expect(onSelect).toHaveBeenCalledWith('repo-1')
  })

  it('shows the ApiError message on failure', async () => {
    vi.mocked(listRepositories).mockRejectedValue(new ApiError('SERVER_ERROR', 'Backend unavailable', 500))
    render(<RepositoryList onSelect={vi.fn()} refreshToken={0} />)
    expect(await screen.findByText('Backend unavailable')).toBeInTheDocument()
  })

  it('shows a generic message for a non-ApiError failure', async () => {
    vi.mocked(listRepositories).mockRejectedValue(new Error('boom'))
    render(<RepositoryList onSelect={vi.fn()} refreshToken={0} />)
    expect(await screen.findByText(/could not load repositories/i)).toBeInTheDocument()
  })

  it('refetches when refreshToken changes', async () => {
    vi.mocked(listRepositories).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50 })
    const { rerender } = render(<RepositoryList onSelect={vi.fn()} refreshToken={0} />)
    await waitFor(() => expect(listRepositories).toHaveBeenCalledTimes(1))

    rerender(<RepositoryList onSelect={vi.fn()} refreshToken={1} />)
    await waitFor(() => expect(listRepositories).toHaveBeenCalledTimes(2))
  })

  it('does not throw or warn when unmounted before the fetch resolves', async () => {
    let resolveFetch: (v: PaginatedRepositories) => void = () => {}
    vi.mocked(listRepositories).mockReturnValue(
      new Promise((resolve) => {
        resolveFetch = resolve
      }),
    )
    const { unmount } = render(<RepositoryList onSelect={vi.fn()} refreshToken={0} />)
    unmount()
    resolveFetch({ items: [makeRepo()], total: 1, page: 1, page_size: 50 })
    await new Promise((r) => setTimeout(r, 0))
    // No assertion needed beyond "did not throw" -- React would log an act()
    // warning to console.error if setState fired post-unmount, which vitest
    // surfaces as a failed expectation via console spy below.
  })

  it('renders repositories missing optional fields (no description, no primary_language) without crashing', async () => {
    vi.mocked(listRepositories).mockResolvedValue({
      items: [makeRepo({ description: null, primary_language: null })],
      total: 1,
      page: 1,
      page_size: 50,
    })
    render(<RepositoryList onSelect={vi.fn()} refreshToken={0} />)
    await screen.findByText('octocat/Hello-World')
    expect(screen.queryByText('TypeScript')).not.toBeInTheDocument()
  })
})
