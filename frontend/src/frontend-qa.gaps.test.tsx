import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import type { RepositoryDetail } from './api'

/**
 * Coverage gaps identified during the frontend E2E QA pass. Each test here
 * exercises a branch that the pre-existing suite never reached.
 */

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api')
  return {
    ...actual,
    listRepositories: vi.fn(),
    ingestRepository: vi.fn(),
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
  ingestRepository,
  listRepositories,
  refreshRepository,
} from './api'

const summary = (over: Record<string, unknown> = {}) => ({
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
  latest_status: 'READY' as const,
  updated_at: '2026-01-01T00:00:00Z',
  ...over,
})

const detail = (over: Partial<RepositoryDetail> = {}): RepositoryDetail => ({
  ...summary(),
  license_name: null,
  topics: [],
  open_issues_count: 0,
  latest_analysis_run: null,
  ...over,
})

beforeEach(() => {
  vi.mocked(listRepositories).mockReset().mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50 })
  vi.mocked(ingestRepository).mockReset()
  vi.mocked(getRepository).mockReset()
  vi.mocked(refreshRepository).mockReset()
  vi.mocked(getAnalysisRunStatus).mockReset().mockReturnValue(new Promise(() => {}))
  vi.mocked(getRepositoryProfile).mockReset().mockReturnValue(new Promise(() => {}))
  vi.mocked(getRepositoryBranches).mockReset().mockReturnValue(new Promise(() => {}))
})

describe('App - repository open: non-ApiError failure', () => {
  it('a plain Error (not ApiError) from getRepository shows the generic fallback and stays on the list', async () => {
    vi.mocked(listRepositories).mockResolvedValue({ items: [summary()], total: 1, page: 1, page_size: 50 })
    vi.mocked(getRepository).mockRejectedValue(new TypeError('network layer blew up'))

    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByText('octocat/Hello-World'))

    expect(await screen.findByText('Could not open this repository.')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /analyze a repository/i })).toBeInTheDocument()
  })
})

describe('App - onboarding form wires straight into the progress view', () => {
  it('a successful ingestRepository transitions App from list to progress', async () => {
    vi.mocked(ingestRepository).mockResolvedValue({
      repository_id: 'repo-1',
      analysis_run_id: 'run-1',
      provider: 'github',
      source_url: '',
      name: 'Hello-World',
      owner: 'octocat',
      selected_branch: null,
      commit_sha: null,
      status: 'QUEUED',
      error_code: null,
      error_message: null,
    })

    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText(/repository url/i), 'https://github.com/octocat/Hello-World')
    await user.click(screen.getByRole('button', { name: /analyze repository/i }))

    expect(await screen.findByText(/analyzing repository/i)).toBeInTheDocument()
    await waitFor(() => expect(getAnalysisRunStatus).toHaveBeenCalledWith('repo-1', 'run-1'))
  })
})

describe('App - non-terminal run statuses all route to progress', () => {
  for (const status of ['QUEUED', 'VALIDATING', 'FETCHING', 'CLONING'] as const) {
    it(`a latest run in ${status} opens the progress view`, async () => {
      vi.mocked(listRepositories).mockResolvedValue({ items: [summary({ latest_status: status })], total: 1, page: 1, page_size: 50 })
      vi.mocked(getRepository).mockResolvedValue(
        detail({
          latest_analysis_run: {
            id: 'run-9',
            status,
            branch_name: 'main',
            commit_sha: null,
            error_code: null,
            error_message: null,
            started_at: '2026-01-01T00:00:00Z',
            completed_at: null,
          },
        }),
      )
      const user = userEvent.setup()
      render(<App />)
      await user.click(await screen.findByText('octocat/Hello-World'))
      expect(await screen.findByText(/analyzing repository/i)).toBeInTheDocument()
      await waitFor(() => expect(getAnalysisRunStatus).toHaveBeenCalledWith('repo-1', 'run-9'))
    })
  }
})

describe('FailureView (via App) - untested branches', () => {
  const openFailed = async (run: Partial<RepositoryDetail['latest_analysis_run'] & object>) => {
    vi.mocked(listRepositories).mockResolvedValue({ items: [summary({ latest_status: 'FAILED' })], total: 1, page: 1, page_size: 50 })
    vi.mocked(getRepository).mockResolvedValue(
      detail({
        latest_analysis_run: {
          id: 'run-1',
          status: 'FAILED',
          branch_name: null,
          commit_sha: null,
          error_code: null,
          error_message: null,
          started_at: '2026-01-01T00:00:00Z',
          completed_at: '2026-01-01T00:01:00Z',
          ...run,
        },
      }),
    )
    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByText('octocat/Hello-World'))
    await screen.findByText(/analysis failed/i)
    return user
  }

  it('renders the fallback sentence when neither error_code nor error_message is present', async () => {
    await openFailed({ error_code: null, error_message: null })
    expect(screen.getByText('The ingestion run did not complete successfully.')).toBeInTheDocument()
  })

  it('a non-ApiError rejection from retry shows the generic retry-failure message and stays retryable', async () => {
    const user = await openFailed({ error_code: 'CLONE_FAILED', error_message: 'boom' })
    vi.mocked(refreshRepository).mockRejectedValue(new Error('socket hang up'))

    const retry = screen.getByRole('button', { name: /retry analysis/i })
    await user.click(retry)

    expect(await screen.findByText('Could not retry analysis.')).toBeInTheDocument()
    expect(retry).not.toBeDisabled()
    // original failure context still visible
    expect(screen.getByText('CLONE_FAILED')).toBeInTheDocument()
    expect(screen.getByText(/boom/)).toBeInTheDocument()
  })
})
