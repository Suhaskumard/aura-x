/**
 * Frontend security regression tests.
 *
 * Every string rendered by the dashboard originates from an untrusted
 * source: the GitHub API, the repository's own metadata, or (transitively)
 * repository file contents. None of it may ever reach the DOM as markup.
 * These tests feed classic XSS payloads through each render path and assert
 * they stay inert text.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type {
  RepositoryDetail,
  RepositoryProfile,
  RepositoryProfileResponse,
  RepositorySummary,
} from './api'

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api')
  return {
    ...actual,
    listRepositories: vi.fn(),
    getRepository: vi.fn(),
    getRepositoryProfile: vi.fn(),
    getRepositoryBranches: vi.fn(),
    getAnalysisRunStatus: vi.fn(),
    refreshRepository: vi.fn(),
  }
})

import App from './App'
import {
  getAnalysisRunStatus,
  getRepository,
  getRepositoryBranches,
  getRepositoryProfile,
  listRepositories,
} from './api'

const IMG = '<img src=x onerror="window.__xss_fired=true">'
const SCRIPT = '<script>window.__xss_fired=true</script>'
const SVG = '"><svg onload="window.__xss_fired=true">'

declare global {
  // eslint-disable-next-line no-var
  var __xss_fired: boolean | undefined
}

function assertNoInjectedMarkup() {
  expect(window.__xss_fired).toBeUndefined()
  expect(document.querySelector('img[onerror]')).toBeNull()
  expect(document.querySelector('svg[onload]')).toBeNull()
  // No <script> beyond those the test runner itself may have inserted.
  expect([...document.querySelectorAll('script')].some((s) => s.textContent?.includes('__xss_fired'))).toBe(false)
}

function summary(overrides: Partial<RepositorySummary> = {}): RepositorySummary {
  return {
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
    ...overrides,
  }
}

function detail(overrides: Partial<RepositoryDetail> = {}): RepositoryDetail {
  return {
    ...summary(overrides),
    license_name: null,
    topics: [],
    open_issues_count: 0,
    latest_analysis_run: null,
    ...overrides,
  }
}

function profile(overrides: Partial<RepositoryProfile> = {}): RepositoryProfile {
  return {
    repository_id: 'repo-1',
    provider: 'github',
    owner: 'octocat',
    repository_name: 'Hello-World',
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
    ...overrides,
  }
}

function profileResponse(p: RepositoryProfile): RepositoryProfileResponse {
  return { repository_id: p.repository_id, analysis_run_id: 'run-1', status: 'READY', profile: p, completed_at: null }
}

describe('frontend XSS resistance', () => {
  beforeEach(() => {
    vi.mocked(listRepositories).mockReset()
    vi.mocked(getRepository).mockReset()
    vi.mocked(getRepositoryProfile).mockReset()
    vi.mocked(getRepositoryBranches).mockReset().mockResolvedValue([])
    vi.mocked(getAnalysisRunStatus).mockReset().mockReturnValue(new Promise(() => {}))
  })
  afterEach(() => {
    delete window.__xss_fired
  })

  it('repository list renders hostile name/owner/description/language as inert text', async () => {
    vi.mocked(listRepositories).mockResolvedValue({
      items: [
        summary({
          owner: `evil${SCRIPT}`,
          name: `repo${IMG}`,
          description: `desc ${SVG}`,
          primary_language: `Lang${IMG}`,
        }),
      ],
      total: 1,
      page: 1,
      page_size: 50,
    })
    render(<App />)
    await screen.findByText(/desc/)
    assertNoInjectedMarkup()
    // The payload survives as visible text (escaped), proving it was treated as data.
    expect(screen.getByText(/desc "><svg onload=/)).toBeInTheDocument()
  })

  it('failure view renders a hostile error_code / error_message as inert text', async () => {
    vi.mocked(listRepositories).mockResolvedValue({
      items: [summary({ latest_status: 'FAILED' })],
      total: 1,
      page: 1,
      page_size: 50,
    })
    vi.mocked(getRepository).mockResolvedValue(
      detail({
        latest_analysis_run: {
          id: 'run-1',
          status: 'FAILED',
          branch_name: null,
          commit_sha: null,
          error_code: `CODE${IMG}`,
          error_message: `boom ${SCRIPT}`,
          started_at: '2026-01-01T00:00:00Z',
          completed_at: '2026-01-01T00:00:00Z',
        },
      }),
    )
    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByText('octocat/Hello-World'))
    await screen.findByText(/analysis failed/i)
    assertNoInjectedMarkup()
    expect(screen.getByText(/boom <script>/)).toBeInTheDocument()
  })

  it('repository profile renders hostile description / dependency / language-key as inert text', async () => {
    vi.mocked(listRepositories).mockResolvedValue({
      items: [summary()],
      total: 1,
      page: 1,
      page_size: 50,
    })
    vi.mocked(getRepository).mockResolvedValue(detail({ latest_analysis_run: null }))
    vi.mocked(getRepositoryProfile).mockResolvedValue(
      profileResponse(
        profile({
          description: `about ${IMG}`,
          languages: { [`Py${SVG}`]: 100 },
          dependencies: [`pkg${SCRIPT}`],
          test_frameworks: [`tf${IMG}`],
        }),
      ),
    )
    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByText('octocat/Hello-World'))
    await screen.findByText(/about/)
    assertNoInjectedMarkup()
    expect(screen.getByText(/pkg<script>/)).toBeInTheDocument()
  })
})
