import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { ApiError } from './api'
import type { RepositoryDetail } from './api'

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

import {
  getAnalysisRunStatus,
  getRepository,
  getRepositoryBranches,
  getRepositoryProfile,
  listRepositories,
  refreshRepository,
} from './api'

function detail(overrides: Partial<RepositoryDetail> = {}): RepositoryDetail {
  return {
    id: 'repo-1',
    provider: 'github',
    owner: 'octocat',
    name: 'Hello-World',
    source_url: 'https://github.com/octocat/Hello-World',
    default_branch: 'main',
    description: null,
    visibility: 'public',
    primary_language: 'TypeScript',
    stargazers_count: 1,
    forks_count: 1,
    latest_status: 'READY',
    updated_at: '2026-01-01T00:00:00Z',
    license_name: null,
    topics: [],
    open_issues_count: 0,
    latest_analysis_run: null,
    ...overrides,
  }
}

describe('App', () => {
  beforeEach(() => {
    vi.mocked(listRepositories).mockReset().mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50 })
    vi.mocked(getRepository).mockReset()
    vi.mocked(refreshRepository).mockReset()
    vi.mocked(getAnalysisRunStatus).mockReset()
    vi.mocked(getRepositoryProfile).mockReset()
    vi.mocked(getRepositoryBranches).mockReset()
  })

  it('renders the repository list and onboarding form on the initial view', async () => {
    render(<App />)
    expect(await screen.findByText(/no repositories analyzed yet/i)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /analyze a repository/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /back to repositories/i })).not.toBeInTheDocument()
  })

  it('selecting a repo with no run or a READY run goes straight to the profile view', async () => {
    vi.mocked(listRepositories).mockResolvedValue({
      items: [
        {
          id: 'repo-1',
          provider: 'github',
          owner: 'octocat',
          name: 'Hello-World',
          source_url: '',
          default_branch: 'main',
          description: null,
          visibility: 'public',
          primary_language: null,
          stargazers_count: 0,
          forks_count: 0,
          latest_status: 'READY',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
      total: 1,
      page: 1,
      page_size: 50,
    })
    vi.mocked(getRepository).mockResolvedValue(detail({ latest_analysis_run: null }))
    vi.mocked(getRepositoryProfile).mockReturnValue(new Promise(() => {}))
    vi.mocked(getRepositoryBranches).mockReturnValue(new Promise(() => {}))

    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByText('octocat/Hello-World'))

    expect(await screen.findByText(/loading repository profile/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /back to repositories/i })).toBeInTheDocument()
  })

  it('selecting a repo with a FAILED run goes to the failure view with error details', async () => {
    vi.mocked(listRepositories).mockResolvedValue({
      items: [
        {
          id: 'repo-1',
          provider: 'github',
          owner: 'octocat',
          name: 'Hello-World',
          source_url: '',
          default_branch: 'main',
          description: null,
          visibility: 'public',
          primary_language: null,
          stargazers_count: 0,
          forks_count: 0,
          latest_status: 'FAILED',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
      total: 1,
      page: 1,
      page_size: 50,
    })
    vi.mocked(getRepository).mockResolvedValue(
      detail({
        latest_analysis_run: {
          id: 'run-1',
          status: 'FAILED',
          branch_name: 'main',
          commit_sha: null,
          error_code: 'CLONE_TIMEOUT',
          error_message: 'Clone took too long',
          started_at: '2026-01-01T00:00:00Z',
          completed_at: '2026-01-01T00:05:00Z',
        },
      }),
    )

    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByText('octocat/Hello-World'))

    expect(await screen.findByText(/analysis failed/i)).toBeInTheDocument()
    expect(screen.getByText('CLONE_TIMEOUT')).toBeInTheDocument()
    expect(screen.getByText(/clone took too long/i)).toBeInTheDocument()
  })

  it('selecting a repo with an in-progress run goes to the progress view', async () => {
    vi.mocked(listRepositories).mockResolvedValue({
      items: [
        {
          id: 'repo-1',
          provider: 'github',
          owner: 'octocat',
          name: 'Hello-World',
          source_url: '',
          default_branch: 'main',
          description: null,
          visibility: 'public',
          primary_language: null,
          stargazers_count: 0,
          forks_count: 0,
          latest_status: 'ANALYZING',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
      total: 1,
      page: 1,
      page_size: 50,
    })
    vi.mocked(getRepository).mockResolvedValue(
      detail({
        latest_analysis_run: {
          id: 'run-1',
          status: 'ANALYZING',
          branch_name: 'main',
          commit_sha: null,
          error_code: null,
          error_message: null,
          started_at: '2026-01-01T00:00:00Z',
          completed_at: null,
        },
      }),
    )
    vi.mocked(getAnalysisRunStatus).mockReturnValue(new Promise(() => {}))

    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByText('octocat/Hello-World'))

    expect(await screen.findByText(/analyzing repository/i)).toBeInTheDocument()
  })

  it('shows a select error (ApiError message) without navigating away from the list', async () => {
    vi.mocked(listRepositories).mockResolvedValue({
      items: [
        {
          id: 'repo-1',
          provider: 'github',
          owner: 'octocat',
          name: 'Hello-World',
          source_url: '',
          default_branch: 'main',
          description: null,
          visibility: 'public',
          primary_language: null,
          stargazers_count: 0,
          forks_count: 0,
          latest_status: 'READY',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
      total: 1,
      page: 1,
      page_size: 50,
    })
    vi.mocked(getRepository).mockRejectedValue(new ApiError('NOT_FOUND', 'Repository was deleted', 404))

    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByText('octocat/Hello-World'))

    expect(await screen.findByText('Repository was deleted')).toBeInTheDocument()
    // Still on the list view.
    expect(screen.getByRole('heading', { name: /analyze a repository/i })).toBeInTheDocument()
  })

  it('"Back to repositories" returns to the list and bumps refreshToken to refetch', async () => {
    vi.mocked(listRepositories).mockResolvedValue({
      items: [
        {
          id: 'repo-1',
          provider: 'github',
          owner: 'octocat',
          name: 'Hello-World',
          source_url: '',
          default_branch: 'main',
          description: null,
          visibility: 'public',
          primary_language: null,
          stargazers_count: 0,
          forks_count: 0,
          latest_status: 'READY',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
      total: 1,
      page: 1,
      page_size: 50,
    })
    vi.mocked(getRepository).mockResolvedValue(detail({ latest_analysis_run: null }))
    vi.mocked(getRepositoryProfile).mockReturnValue(new Promise(() => {}))
    vi.mocked(getRepositoryBranches).mockReturnValue(new Promise(() => {}))

    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByText('octocat/Hello-World'))
    await screen.findByText(/loading repository profile/i)

    await user.click(screen.getByRole('button', { name: /back to repositories/i }))

    expect(screen.getByRole('heading', { name: /analyze a repository/i })).toBeInTheDocument()
    await waitFor(() => expect(listRepositories).toHaveBeenCalledTimes(2))
  })

  it('retrying a failed analysis moves to the progress view on success', async () => {
    vi.mocked(listRepositories).mockResolvedValue({
      items: [
        {
          id: 'repo-1',
          provider: 'github',
          owner: 'octocat',
          name: 'Hello-World',
          source_url: '',
          default_branch: 'main',
          description: null,
          visibility: 'public',
          primary_language: null,
          stargazers_count: 0,
          forks_count: 0,
          latest_status: 'FAILED',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
      total: 1,
      page: 1,
      page_size: 50,
    })
    vi.mocked(getRepository).mockResolvedValue(
      detail({
        latest_analysis_run: {
          id: 'run-1',
          status: 'FAILED',
          branch_name: 'main',
          commit_sha: null,
          error_code: 'CLONE_TIMEOUT',
          error_message: 'Clone took too long',
          started_at: '2026-01-01T00:00:00Z',
          completed_at: '2026-01-01T00:05:00Z',
        },
      }),
    )
    vi.mocked(refreshRepository).mockResolvedValue({
      repository_id: 'repo-1',
      analysis_run_id: 'run-2',
      provider: 'github',
      source_url: '',
      name: '',
      owner: '',
      selected_branch: 'main',
      commit_sha: null,
      status: 'QUEUED',
      error_code: null,
      error_message: null,
    })
    vi.mocked(getAnalysisRunStatus).mockReturnValue(new Promise(() => {}))

    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByText('octocat/Hello-World'))
    await screen.findByText(/analysis failed/i)

    await user.click(screen.getByRole('button', { name: /retry analysis/i }))
    expect(await screen.findByText(/analyzing repository/i)).toBeInTheDocument()
  })

  it('retrying a failed analysis shows an error and stays retryable on failure', async () => {
    vi.mocked(listRepositories).mockResolvedValue({
      items: [
        {
          id: 'repo-1',
          provider: 'github',
          owner: 'octocat',
          name: 'Hello-World',
          source_url: '',
          default_branch: 'main',
          description: null,
          visibility: 'public',
          primary_language: null,
          stargazers_count: 0,
          forks_count: 0,
          latest_status: 'FAILED',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
      total: 1,
      page: 1,
      page_size: 50,
    })
    vi.mocked(getRepository).mockResolvedValue(
      detail({
        latest_analysis_run: {
          id: 'run-1',
          status: 'FAILED',
          branch_name: 'main',
          commit_sha: null,
          error_code: 'CLONE_TIMEOUT',
          error_message: 'Clone took too long',
          started_at: '2026-01-01T00:00:00Z',
          completed_at: '2026-01-01T00:05:00Z',
        },
      }),
    )
    vi.mocked(refreshRepository).mockRejectedValue(new ApiError('RATE_LIMITED', 'Too many requests', 429))

    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByText('octocat/Hello-World'))
    await screen.findByText(/analysis failed/i)

    const retryButton = screen.getByRole('button', { name: /retry analysis/i })
    await user.click(retryButton)

    expect(await screen.findByText('Too many requests')).toBeInTheDocument()
    expect(retryButton).not.toBeDisabled()
    // Still showing the original failure details.
    expect(screen.getByText('CLONE_TIMEOUT')).toBeInTheDocument()
  })
})
