import type { Page, Route } from '@playwright/test'

export const API = 'http://localhost:8000'

/** ---- response fixture builders (mirror backend/app/api/v1/schemas.py) ---- */

export function repoSummary(over: Partial<Record<string, unknown>> = {}) {
  return {
    id: 'repo-1',
    provider: 'github',
    owner: 'octocat',
    name: 'Hello-World',
    source_url: 'https://github.com/octocat/Hello-World',
    default_branch: 'master',
    description: 'My first repository on GitHub!',
    visibility: 'public',
    primary_language: 'C',
    stargazers_count: 2500,
    forks_count: 2000,
    latest_status: 'READY',
    updated_at: '2024-01-01T00:00:00Z',
    ...over,
  }
}

export function repoList(items: unknown[]) {
  return { items, total: items.length, page: 1, page_size: 50 }
}

/** A page slice of a synthetic dataset of `total` repos, matching the backend
 *  `GET /api/v1/repositories?page=&page_size=` contract (updated_at desc). */
export function repoPage(total: number, page: number, pageSize = 50) {
  const start = (page - 1) * pageSize
  const count = Math.max(0, Math.min(pageSize, total - start))
  const items = Array.from({ length: count }, (_, k) => {
    const n = start + k + 1
    return repoSummary({ id: `repo-${n}`, owner: 'octocat', name: `repo-${n}`, description: null, primary_language: null })
  })
  return { items, total, page, page_size: pageSize }
}

/** Read `page` out of a request URL's query string. */
export function pageParam(url: string): number {
  return Number(new URL(url).searchParams.get('page') ?? '1')
}

export function repoDetail(over: Partial<Record<string, unknown>> = {}) {
  return {
    ...repoSummary(),
    license_name: 'MIT',
    topics: ['octocat', 'demo'],
    open_issues_count: 3,
    latest_analysis_run: {
      id: 'run-1',
      status: 'READY',
      branch_name: 'master',
      commit_sha: '7fd1a60b01f91b314f59955a4e4d4e80d8edf11d',
      error_code: null,
      error_message: null,
      started_at: '2024-01-01T00:00:00Z',
      completed_at: '2024-01-01T00:05:00Z',
    },
    ...over,
  }
}

export function runStatus(over: Partial<Record<string, unknown>> = {}) {
  return {
    id: 'run-1',
    repository_id: 'repo-1',
    status: 'ANALYZING',
    branch_name: 'master',
    commit_sha: null,
    error_code: null,
    error_message: null,
    started_at: '2024-01-01T00:00:00Z',
    completed_at: null,
    ...over,
  }
}

export function branches(names: Array<{ name: string; is_default?: boolean }> = [{ name: 'master', is_default: true }]) {
  return names.map((b, i) => ({
    name: b.name,
    head_commit_sha: `${'a'.repeat(39)}${i}`,
    is_default: !!b.is_default,
  }))
}

export function profileResponse(profileOver: Partial<Record<string, unknown>> = {}) {
  return {
    repository_id: 'repo-1',
    analysis_run_id: 'run-1',
    status: 'READY',
    completed_at: '2024-01-01T00:05:00Z',
    profile: {
      repository_id: 'repo-1',
      provider: 'github',
      owner: 'octocat',
      repository_name: 'Hello-World',
      source_url: 'https://github.com/octocat/Hello-World',
      selected_branch: 'master',
      default_branch: 'master',
      commit_sha: '7fd1a60b01f91b314f59955a4e4d4e80d8edf11d',
      status: 'READY',
      description: 'My first repository on GitHub!',
      visibility: 'public',
      stargazers_count: 2500,
      forks_count: 2000,
      languages: { Python: 90000, TypeScript: 45000, CSS: 5000 },
      test_frameworks: ['pytest', 'vitest'],
      test_directories: ['tests/', 'src/__tests__/'],
      dependencies: ['react', 'react-dom', 'fastapi'],
      file_inventory: { total_files: 128, total_size_bytes: 1_500_000, by_category: { source: 90, test: 20, config: 18 } },
      git_history_summary: { commit_count: 42, most_recent_commit_at: '2024-01-01T00:00:00Z' },
      updated_at: '2024-01-01T00:05:00Z',
      ...profileOver,
    },
  }
}

export function ingestResponse(over: Partial<Record<string, unknown>> = {}) {
  return {
    repository_id: 'repo-1',
    provider: 'github',
    source_url: 'https://github.com/octocat/Hello-World',
    name: 'Hello-World',
    owner: 'octocat',
    selected_branch: null,
    commit_sha: null,
    status: 'QUEUED',
    analysis_run_id: 'run-1',
    error_code: null,
    error_message: null,
    ...over,
  }
}

/** ---- routing helpers ---- */

type Handler = (route: Route) => unknown | Promise<unknown>

/** Intercept every backend API call; `map` keys are matched as substrings of the URL path. */
export async function mockApi(page: Page, map: Array<{ match: RegExp | string; handler: Handler }>) {
  await page.route(`${API}/api/v1/**`, async (route) => {
    const url = route.request().url()
    for (const { match, handler } of map) {
      if (typeof match === 'string' ? url.includes(match) : match.test(url)) {
        return handler(route)
      }
    }
    // default: empty list / 404 so nothing hangs
    return route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ code: 'REPOSITORY_NOT_FOUND', message: 'not found' }) })
  })
}

export const json = (body: unknown, status = 200) => (route: Route) =>
  route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })

export const jsonAfter = (ms: number, body: unknown, status = 200) => async (route: Route) => {
  await new Promise((r) => setTimeout(r, ms))
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

export const raw = (body: string, status = 200, contentType = 'text/html') => (route: Route) =>
  route.fulfill({ status, contentType, body })

export const abort = () => (route: Route) => route.abort('failed')

/** Collect console errors / page errors for assertions. */
export function collectConsole(page: Page) {
  const errors: string[] = []
  const warnings: string[] = []
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push(m.text())
    if (m.type() === 'warning') warnings.push(m.text())
  })
  page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`))
  return { errors, warnings }
}

/** Fail the test if a JS dialog (alert/confirm from an XSS payload) ever fires. */
export function trapDialogs(page: Page) {
  const fired: string[] = []
  page.on('dialog', async (d) => {
    fired.push(`${d.type()}: ${d.message()}`)
    await d.dismiss().catch(() => {})
  })
  return fired
}
