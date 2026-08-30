import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { RepositoryProfile, RepositoryProfileResponse } from '../api'
import RepositoryProfileView from './RepositoryProfileView'

/** Coverage gaps in RepositoryProfileView not touched by the existing suite. */

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api')
  return {
    ...actual,
    getRepositoryProfile: vi.fn(),
    getRepositoryBranches: vi.fn(),
    refreshRepository: vi.fn(),
  }
})

import { getRepositoryBranches, getRepositoryProfile, refreshRepository } from '../api'

function makeProfile(over: Partial<RepositoryProfile> = {}): RepositoryProfile {
  return {
    repository_id: 'repo-1',
    provider: 'github',
    owner: 'octocat',
    repository_name: 'Hello-World',
    source_url: 'x',
    selected_branch: 'main',
    default_branch: 'main',
    commit_sha: 'a'.repeat(40),
    status: 'READY',
    description: null,
    visibility: 'public',
    stargazers_count: 1,
    forks_count: 1,
    languages: {},
    test_frameworks: [],
    test_directories: [],
    dependencies: [],
    file_inventory: { total_files: 0, total_size_bytes: 0, by_category: {} },
    git_history_summary: { commit_count: 0, most_recent_commit_at: null },
    updated_at: '2026-01-01T00:00:00Z',
    ...over,
  }
}
const resp = (p: RepositoryProfile): RepositoryProfileResponse => ({
  repository_id: 'repo-1',
  analysis_run_id: 'run-1',
  status: 'READY',
  profile: p,
  completed_at: null,
})

beforeEach(() => {
  vi.mocked(getRepositoryProfile).mockReset()
  vi.mocked(getRepositoryBranches).mockReset().mockResolvedValue([{ name: 'main', head_commit_sha: 'a'.repeat(40), is_default: true }])
  vi.mocked(refreshRepository).mockReset()
})

describe('formatBytes - MB branch', () => {
  it('renders megabyte-scale sizes with the MB unit', async () => {
    vi.mocked(getRepositoryProfile).mockResolvedValue(resp(makeProfile({ file_inventory: { total_files: 3, total_size_bytes: 3_500_000, by_category: {} } })))
    render(<RepositoryProfileView repositoryId="repo-1" onRefreshStarted={vi.fn()} />)
    expect(await screen.findByText('3.3 MB')).toBeInTheDocument()
  })
})

describe('null-ish fact fields fall back to an em dash', () => {
  it('renders "—" for null visibility / stars / forks / commit and never "null" or "NaN"', async () => {
    vi.mocked(getRepositoryProfile).mockResolvedValue(
      resp(
        makeProfile({
          visibility: null,
          stargazers_count: null,
          forks_count: null,
          commit_sha: null,
          selected_branch: null,
        }),
      ),
    )
    const { container } = render(<RepositoryProfileView repositoryId="repo-1" onRefreshStarted={vi.fn()} />)
    await screen.findByText('octocat/Hello-World')
    const facts = container.querySelector('.profile-facts')!
    expect(facts.textContent).not.toMatch(/null|NaN|undefined/)
    // commit dd + the four null facts + null branch => several em dashes
    expect(facts.querySelectorAll('dd')).not.toHaveLength(0)
    expect(facts.textContent).toContain('—')
  })
})

describe('git history summary', () => {
  it('renders the analysed commit count', async () => {
    vi.mocked(getRepositoryProfile).mockResolvedValue(resp(makeProfile({ git_history_summary: { commit_count: 137, most_recent_commit_at: null } })))
    render(<RepositoryProfileView repositoryId="repo-1" onRefreshStarted={vi.fn()} />)
    await screen.findByText('octocat/Hello-World')
    expect(screen.getByText('Commits analyzed').closest('div')!.textContent).toContain('137')
  })
})

describe('non-ApiError rejections use the generic copy', () => {
  it('a plain Error while loading the profile shows the generic load-failure message', async () => {
    vi.mocked(getRepositoryProfile).mockRejectedValue(new TypeError('boom'))
    render(<RepositoryProfileView repositoryId="repo-1" onRefreshStarted={vi.fn()} />)
    expect(await screen.findByText('Could not load the repository profile.')).toBeInTheDocument()
  })

  it('a plain Error from re-analyze shows the generic re-analysis-failure message and re-enables the button', async () => {
    vi.mocked(getRepositoryProfile).mockResolvedValue(resp(makeProfile()))
    vi.mocked(refreshRepository).mockRejectedValue(new Error('socket reset'))
    const user = userEvent.setup()
    render(<RepositoryProfileView repositoryId="repo-1" onRefreshStarted={vi.fn()} />)
    await screen.findByText('octocat/Hello-World')
    const btn = screen.getByRole('button', { name: /re-analyze this branch/i })
    await user.click(btn)
    expect(await screen.findByText('Could not start re-analysis.')).toBeInTheDocument()
    expect(btn).not.toBeDisabled()
  })
})
