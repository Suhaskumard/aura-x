import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ApiError,
  API_BASE_URL,
  getAnalysisRunStatus,
  getRepository,
  getRepositoryBranches,
  getRepositoryProfile,
  ingestRepository,
  listRepositories,
  refreshRepository,
} from './api'

function jsonResponse(body: unknown, init: { status?: number; ok?: boolean } = {}) {
  const status = init.status ?? 200
  return {
    ok: init.ok ?? (status >= 200 && status < 300),
    status,
    json: () => Promise.resolve(body),
  } as Response
}

describe('api client', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('resolves with the parsed body on a 200 response', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ items: [], total: 0, page: 1, page_size: 20 }))
    const result = await listRepositories()
    expect(result.total).toBe(0)
    expect(fetch).toHaveBeenCalledWith(
      `${API_BASE_URL}/api/v1/repositories?page=1&page_size=20`,
      expect.objectContaining({ headers: expect.objectContaining({ 'Content-Type': 'application/json' }) }),
    )
  })

  it('wraps a fetch/network failure in an ApiError with code NETWORK_ERROR', async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError('Failed to fetch'))
    await expect(listRepositories()).rejects.toMatchObject({
      code: 'NETWORK_ERROR',
      status: 0,
    })
    await expect(listRepositories()).rejects.toBeInstanceOf(ApiError)
  })

  it('surfaces the backend code/message for a JSON error body', async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ code: 'NOT_FOUND', message: 'Repository not found' }, { status: 404 }),
    )
    await expect(getRepository('abc')).rejects.toMatchObject({
      code: 'NOT_FOUND',
      message: 'Repository not found',
      status: 404,
    })
  })

  it('falls back to a generic message when the error body is not JSON', async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: false,
      status: 500,
      json: () => Promise.reject(new SyntaxError('Unexpected token')),
    } as unknown as Response)
    await expect(getRepositoryProfile('abc')).rejects.toMatchObject({
      code: 'UNKNOWN_ERROR',
      message: 'Request failed with status 500',
      status: 500,
    })
  })

  it('falls back to a generic message when the error body is JSON but missing code/message', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({}, { status: 422 }))
    await expect(getRepositoryBranches('abc')).rejects.toMatchObject({
      code: 'UNKNOWN_ERROR',
      message: 'Request failed with status 422',
      status: 422,
    })
  })

  it.each([400, 401, 403, 404, 409, 422, 429, 500, 502, 503])(
    'propagates status %d as a rejected ApiError',
    async (status) => {
      vi.mocked(fetch).mockResolvedValue(jsonResponse({ code: `ERR_${status}`, message: 'boom' }, { status }))
      await expect(getRepository('abc')).rejects.toMatchObject({ status })
    },
  )

  it('sends the repository URL and branch on ingestRepository', async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({
        repository_id: 'r1',
        provider: 'github',
        source_url: 'https://github.com/octocat/Hello-World',
        name: 'Hello-World',
        owner: 'octocat',
        selected_branch: null,
        commit_sha: null,
        status: 'QUEUED',
        analysis_run_id: 'run1',
        error_code: null,
        error_message: null,
      }),
    )
    await ingestRepository('https://github.com/octocat/Hello-World', 'main')
    expect(fetch).toHaveBeenCalledWith(
      `${API_BASE_URL}/api/v1/repositories/github`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ repository_url: 'https://github.com/octocat/Hello-World', branch: 'main' }),
      }),
    )
  })

  it('sends branch: null when no branch is provided to ingestRepository', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({}))
    await ingestRepository('https://github.com/octocat/Hello-World')
    expect(fetch).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ body: JSON.stringify({ repository_url: 'https://github.com/octocat/Hello-World', branch: null }) }),
    )
  })

  it('posts to the refresh endpoint with the repository id in the path', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({}))
    await refreshRepository('repo-123', 'develop')
    expect(fetch).toHaveBeenCalledWith(
      `${API_BASE_URL}/api/v1/repositories/repo-123/refresh`,
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ branch: 'develop' }) }),
    )
  })

  it('gets analysis run status from the nested path', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ id: 'run1', status: 'READY' }))
    await getAnalysisRunStatus('repo-1', 'run-1')
    expect(fetch).toHaveBeenCalledWith(
      `${API_BASE_URL}/api/v1/repositories/repo-1/analysis-runs/run-1`,
      expect.anything(),
    )
  })
})
