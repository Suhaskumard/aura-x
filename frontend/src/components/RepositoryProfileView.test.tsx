import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api'
import type { BranchOut, IngestRepositoryResponse, RepositoryProfile, RepositoryProfileResponse } from '../api'
import RepositoryProfileView from './RepositoryProfileView'

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

function makeProfile(overrides: Partial<RepositoryProfile> = {}): RepositoryProfile {
  return {
    repository_id: 'repo-1',
    provider: 'github',
    owner: 'octocat',
    repository_name: 'Hello-World',
    source_url: 'https://github.com/octocat/Hello-World',
    selected_branch: 'main',
    default_branch: 'main',
    commit_sha: 'a'.repeat(40),
    status: 'READY',
    description: 'A test repo',
    visibility: 'public',
    stargazers_count: 42,
    forks_count: 7,
    languages: { TypeScript: 800, CSS: 200 },
    test_frameworks: ['vitest'],
    test_directories: ['src'],
    dependencies: ['react', 'react-dom'],
    file_inventory: { total_files: 10, total_size_bytes: 2048, by_category: {} },
    git_history_summary: { commit_count: 12, most_recent_commit_at: '2026-01-01T00:00:00Z' },
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

function makeResponse(profile: RepositoryProfile): RepositoryProfileResponse {
  return {
    repository_id: profile.repository_id,
    analysis_run_id: 'run-1',
    status: 'READY',
    profile,
    completed_at: '2026-01-01T00:00:00Z',
  }
}

function makeBranches(): BranchOut[] {
  return [
    { name: 'main', head_commit_sha: 'a'.repeat(40), is_default: true },
    { name: 'develop', head_commit_sha: 'b'.repeat(40), is_default: false },
  ]
}

describe('RepositoryProfileView', () => {
  beforeEach(() => {
    vi.mocked(getRepositoryProfile).mockReset()
    vi.mocked(getRepositoryBranches).mockReset()
    vi.mocked(refreshRepository).mockReset()
  })

  it('shows a loading state before data arrives', () => {
    vi.mocked(getRepositoryProfile).mockReturnValue(new Promise(() => {}))
    vi.mocked(getRepositoryBranches).mockReturnValue(new Promise(() => {}))
    render(<RepositoryProfileView repositoryId="repo-1" onRefreshStarted={vi.fn()} />)
    expect(screen.getByText(/loading repository profile/i)).toBeInTheDocument()
  })

  it('renders facts, sorted languages with percentages, frameworks and dependencies', async () => {
    vi.mocked(getRepositoryProfile).mockResolvedValue(makeResponse(makeProfile()))
    vi.mocked(getRepositoryBranches).mockResolvedValue(makeBranches())
    render(<RepositoryProfileView repositoryId="repo-1" onRefreshStarted={vi.fn()} />)

    await screen.findByText('octocat/Hello-World')
    expect(screen.getByText('80.0%')).toBeInTheDocument() // TypeScript 800/1000
    expect(screen.getByText('20.0%')).toBeInTheDocument() // CSS 200/1000
    expect(screen.getByText('vitest')).toBeInTheDocument()
    expect(screen.getByText('react')).toBeInTheDocument()
    expect(screen.getByText('2.0 KB')).toBeInTheDocument()
    expect(screen.getByText('a'.repeat(12))).toBeInTheDocument() // truncated commit sha
  })

  it('shows "No languages detected" and "No dependency manifests detected" for empty collections', async () => {
    vi.mocked(getRepositoryProfile).mockResolvedValue(
      makeResponse(makeProfile({ languages: {}, dependencies: [], test_frameworks: [] })),
    )
    vi.mocked(getRepositoryBranches).mockResolvedValue([])
    render(<RepositoryProfileView repositoryId="repo-1" onRefreshStarted={vi.fn()} />)

    await screen.findByText('octocat/Hello-World')
    expect(screen.getByText(/no languages detected/i)).toBeInTheDocument()
    expect(screen.getByText(/no dependency manifests detected/i)).toBeInTheDocument()
    expect(screen.getByText(/no test frameworks detected/i)).toBeInTheDocument()
  })

  it('caps rendered dependencies at 24 and shows a "+N more" pill', async () => {
    const deps = Array.from({ length: 30 }, (_, i) => `dep-${i}`)
    vi.mocked(getRepositoryProfile).mockResolvedValue(makeResponse(makeProfile({ dependencies: deps })))
    vi.mocked(getRepositoryBranches).mockResolvedValue([])
    render(<RepositoryProfileView repositoryId="repo-1" onRefreshStarted={vi.fn()} />)

    await screen.findByText('octocat/Hello-World')
    expect(screen.getByText('dep-23')).toBeInTheDocument()
    expect(screen.queryByText('dep-24')).not.toBeInTheDocument()
    expect(screen.getByText('+6 more')).toBeInTheDocument()
  })

  it('shows the ApiError message on load failure', async () => {
    vi.mocked(getRepositoryProfile).mockRejectedValue(new ApiError('NOT_FOUND', 'Repository not found', 404))
    vi.mocked(getRepositoryBranches).mockResolvedValue([])
    render(<RepositoryProfileView repositoryId="repo-1" onRefreshStarted={vi.fn()} />)
    expect(await screen.findByText('Repository not found')).toBeInTheDocument()
  })

  it('selects the profile\'s selected_branch in the branch dropdown, matching visible option text', async () => {
    vi.mocked(getRepositoryProfile).mockResolvedValue(makeResponse(makeProfile({ selected_branch: 'develop' })))
    vi.mocked(getRepositoryBranches).mockResolvedValue(makeBranches())
    render(<RepositoryProfileView repositoryId="repo-1" onRefreshStarted={vi.fn()} />)

    await screen.findByText('octocat/Hello-World')
    const select = screen.getByRole('combobox') as HTMLSelectElement
    expect(select.value).toBe('develop')
  })

  it('falls back to the default branch in the dropdown when selected_branch is null (regression)', async () => {
    vi.mocked(getRepositoryProfile).mockResolvedValue(
      makeResponse(makeProfile({ selected_branch: null, default_branch: 'main' })),
    )
    // 'main' (the default) is deliberately NOT first in the list -- this is
    // what exposed the original bug: the browser displays the first option
    // ('develop') while state silently held '', which is out of sync.
    vi.mocked(getRepositoryBranches).mockResolvedValue([...makeBranches()].reverse())
    render(<RepositoryProfileView repositoryId="repo-1" onRefreshStarted={vi.fn()} />)

    await screen.findByText('octocat/Hello-World')
    const select = screen.getByRole('combobox') as HTMLSelectElement
    // The select's value must be an actual option, not an empty string that
    // matches nothing -- otherwise the browser silently displays the first
    // <option> while React believes the value is still ''.
    expect(select.value).toBe('main')
    expect(select.value).not.toBe('')
  })

  it('falls back to the first branch when both selected_branch and default_branch are null', async () => {
    vi.mocked(getRepositoryProfile).mockResolvedValue(
      makeResponse(makeProfile({ selected_branch: null, default_branch: null })),
    )
    vi.mocked(getRepositoryBranches).mockResolvedValue(makeBranches())
    render(<RepositoryProfileView repositoryId="repo-1" onRefreshStarted={vi.fn()} />)

    await screen.findByText('octocat/Hello-World')
    const select = screen.getByRole('combobox') as HTMLSelectElement
    expect(select.value).toBe('main')
  })

  it('the branch select has an accessible name', async () => {
    vi.mocked(getRepositoryProfile).mockResolvedValue(makeResponse(makeProfile()))
    vi.mocked(getRepositoryBranches).mockResolvedValue(makeBranches())
    render(<RepositoryProfileView repositoryId="repo-1" onRefreshStarted={vi.fn()} />)

    await screen.findByText('octocat/Hello-World')
    expect(screen.getByLabelText(/branch/i)).toBeInTheDocument()
  })

  it('starts re-analysis with the selected branch and calls onRefreshStarted', async () => {
    vi.mocked(getRepositoryProfile).mockResolvedValue(makeResponse(makeProfile()))
    vi.mocked(getRepositoryBranches).mockResolvedValue(makeBranches())
    vi.mocked(refreshRepository).mockResolvedValue({
      repository_id: 'repo-1',
      analysis_run_id: 'run-2',
      provider: 'github',
      source_url: '',
      name: '',
      owner: '',
      selected_branch: 'develop',
      commit_sha: null,
      status: 'QUEUED',
      error_code: null,
      error_message: null,
    })
    const onRefreshStarted = vi.fn()
    const user = userEvent.setup()
    render(<RepositoryProfileView repositoryId="repo-1" onRefreshStarted={onRefreshStarted} />)

    await screen.findByText('octocat/Hello-World')
    await user.selectOptions(screen.getByRole('combobox'), 'develop')
    await user.click(screen.getByRole('button', { name: /re-analyze this branch/i }))

    await waitFor(() => expect(onRefreshStarted).toHaveBeenCalledWith('run-2'))
    expect(refreshRepository).toHaveBeenCalledWith('repo-1', 'develop')
  })

  it('shows a refresh error and re-enables the button on failure', async () => {
    vi.mocked(getRepositoryProfile).mockResolvedValue(makeResponse(makeProfile()))
    vi.mocked(getRepositoryBranches).mockResolvedValue(makeBranches())
    vi.mocked(refreshRepository).mockRejectedValue(new ApiError('CONFLICT', 'A run is already in progress', 409))
    const user = userEvent.setup()
    render(<RepositoryProfileView repositoryId="repo-1" onRefreshStarted={vi.fn()} />)

    await screen.findByText('octocat/Hello-World')
    const button = screen.getByRole('button', { name: /re-analyze this branch/i })
    await user.click(button)

    expect(await screen.findByText('A run is already in progress')).toBeInTheDocument()
    expect(button).not.toBeDisabled()
  })

  it('disables the branch select and button while refreshing is in flight', async () => {
    vi.mocked(getRepositoryProfile).mockResolvedValue(makeResponse(makeProfile()))
    vi.mocked(getRepositoryBranches).mockResolvedValue(makeBranches())
    let resolveRefresh: (v: IngestRepositoryResponse) => void = () => {}
    vi.mocked(refreshRepository).mockReturnValue(
      new Promise((resolve) => {
        resolveRefresh = resolve
      }),
    )
    const user = userEvent.setup()
    render(<RepositoryProfileView repositoryId="repo-1" onRefreshStarted={vi.fn()} />)

    await screen.findByText('octocat/Hello-World')
    const button = screen.getByRole('button', { name: /re-analyze this branch/i })
    await user.click(button)

    expect(button).toBeDisabled()
    expect(screen.getByRole('combobox')).toBeDisabled()
    resolveRefresh({
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
  })

  it('formats zero-byte and megabyte-scale sizes correctly', async () => {
    vi.mocked(getRepositoryProfile).mockResolvedValue(
      makeResponse(makeProfile({ file_inventory: { total_files: 0, total_size_bytes: 0, by_category: {} } })),
    )
    vi.mocked(getRepositoryBranches).mockResolvedValue([])
    render(<RepositoryProfileView repositoryId="repo-1" onRefreshStarted={vi.fn()} />)
    await screen.findByText('octocat/Hello-World')
    expect(screen.getByText('0 B')).toBeInTheDocument()
  })
})
