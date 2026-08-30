import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { ApiError } from './api'
import type { RepositoryDetail, RepositoryProfileResponse, RepositorySummary } from './api'

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api')
  return {
    ...actual,
    listRepositories: vi.fn(),
    getRepository: vi.fn(),
    refreshRepository: vi.fn(),
    getAnalysisRunStatus: vi.fn(),
    getRepositoryProfile: vi.fn(),
    getRepositoryBranches: vi.fn(),
  }
})

import { getRepository, getRepositoryBranches, getRepositoryProfile, listRepositories } from './api'

function summary(id: string, owner: string, name: string): RepositorySummary {
  return {
    id,
    provider: 'github',
    owner,
    name,
    source_url: '',
    default_branch: 'main',
    description: null,
    visibility: 'public',
    primary_language: null,
    stargazers_count: 0,
    forks_count: 0,
    latest_status: 'READY',
    updated_at: '2026-01-01T00:00:00Z',
  }
}

function detail(id: string, owner: string, name: string): RepositoryDetail {
  return {
    ...summary(id, owner, name),
    license_name: null,
    topics: [],
    open_issues_count: 0,
    latest_analysis_run: null,
  }
}

function profileResponse(id: string, owner: string, name: string): RepositoryProfileResponse {
  return {
    repository_id: id,
    analysis_run_id: 'run-x',
    status: 'READY',
    completed_at: '2026-01-01T00:00:00Z',
    profile: {
      repository_id: id,
      provider: 'github',
      owner,
      repository_name: name,
      source_url: '',
      selected_branch: 'main',
      default_branch: 'main',
      commit_sha: null,
      status: 'READY',
      description: null,
      visibility: 'public',
      stargazers_count: 0,
      forks_count: 0,
      languages: {},
      test_frameworks: [],
      test_directories: [],
      dependencies: [],
      file_inventory: { total_files: 0, total_size_bytes: 0, by_category: {} },
      git_history_summary: { commit_count: 0, most_recent_commit_at: null },
      updated_at: '2026-01-01T00:00:00Z',
    },
  }
}

describe('App — repository-open race / stale response', () => {
  beforeEach(() => {
    vi.mocked(listRepositories).mockReset().mockResolvedValue({
      items: [summary('repo-1', 'one', 'ONE'), summary('repo-2', 'two', 'TWO')],
      total: 2,
      page: 1,
      page_size: 50,
    })
    vi.mocked(getRepository).mockReset()
    vi.mocked(getRepositoryProfile)
      .mockReset()
      .mockImplementation((id: string) =>
        Promise.resolve(id === 'repo-2' ? profileResponse('repo-2', 'two', 'TWO') : profileResponse('repo-1', 'one', 'ONE')),
      )
    vi.mocked(getRepositoryBranches).mockReset().mockResolvedValue([])
  })

  it('a slow earlier getRepository must not overwrite the view chosen by a later click', async () => {
    let resolveRepo1: (d: RepositoryDetail) => void = () => {}
    vi.mocked(getRepository).mockImplementation((id: string) => {
      if (id === 'repo-1') return new Promise<RepositoryDetail>((r) => (resolveRepo1 = r))
      return Promise.resolve(detail('repo-2', 'two', 'TWO'))
    })

    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByText('one/ONE')) // slow — repo-1 in flight
    await user.click(screen.getByText('two/TWO')) // fast — resolves, navigates to repo-2

    expect(await screen.findByRole('heading', { name: 'two/TWO' })).toBeInTheDocument()

    // The stale repo-1 response now arrives last — it must be ignored.
    await act(async () => {
      resolveRepo1(detail('repo-1', 'one', 'ONE'))
      await new Promise((r) => setTimeout(r, 10))
    })

    expect(screen.getByRole('heading', { name: 'two/TWO' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'one/ONE' })).not.toBeInTheDocument()
    expect(getRepositoryProfile).not.toHaveBeenCalledWith('repo-1')
  })

  it('a stale getRepository rejection does not clobber the view chosen by a newer click', async () => {
    let rejectRepo1: (e: unknown) => void = () => {}
    vi.mocked(getRepository).mockImplementation((id: string) => {
      if (id === 'repo-1') return new Promise<RepositoryDetail>((_, rej) => (rejectRepo1 = rej))
      // repo-2 has a FAILED run so the newer click lands on the failure view,
      // which *does* render error text — making a stale error leak observable.
      return Promise.resolve({
        ...detail('repo-2', 'two', 'TWO'),
        latest_analysis_run: {
          id: 'run-2',
          status: 'FAILED' as const,
          branch_name: 'main',
          commit_sha: null,
          error_code: 'CLONE_TIMEOUT',
          error_message: 'repo-2 clone timed out',
          started_at: '2026-01-01T00:00:00Z',
          completed_at: '2026-01-01T00:05:00Z',
        },
      })
    })

    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByText('one/ONE'))
    await user.click(screen.getByText('two/TWO'))
    await screen.findByText(/repo-2 clone timed out/)

    await act(async () => {
      rejectRepo1(new ApiError('NOT_FOUND', 'repo-1 is gone', 404))
      await new Promise((r) => setTimeout(r, 10))
    })

    // Returning to the list must not surface the stale error from a
    // repository the user has since navigated away from.
    await user.click(screen.getByRole('button', { name: /back to repositories/i }))
    expect(await screen.findByText('one/ONE')).toBeInTheDocument()
    expect(screen.queryByText(/repo-1 is gone/)).not.toBeInTheDocument()
  })
})
