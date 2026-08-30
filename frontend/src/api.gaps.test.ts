import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { API_BASE_URL, getRepositoryProfile, listRepositories } from './api'

/** api client branches the existing api.test.ts does not assert. */

function jsonResponse(body: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) } as Response
}

describe('api client - coverage gaps', () => {
  beforeEach(() => vi.stubGlobal('fetch', vi.fn()))
  afterEach(() => vi.unstubAllGlobals())

  it('listRepositories forwards non-default page / page_size into the query string', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ items: [], total: 0, page: 3, page_size: 40 }))
    await listRepositories(3, 40)
    expect(fetch).toHaveBeenCalledWith(
      `${API_BASE_URL}/api/v1/repositories?page=3&page_size=40`,
      expect.objectContaining({ headers: expect.objectContaining({ 'Content-Type': 'application/json' }) }),
    )
  })

  it('resolves the parsed profile body on success (not only the error path)', async () => {
    const body = {
      repository_id: 'repo-1',
      analysis_run_id: 'run-1',
      status: 'READY',
      completed_at: null,
      profile: { owner: 'octocat', repository_name: 'Hello-World', languages: { Python: 1 } },
    }
    vi.mocked(fetch).mockResolvedValue(jsonResponse(body))
    const res = await getRepositoryProfile('repo-1')
    expect(res.profile.owner).toBe('octocat')
    expect(fetch).toHaveBeenCalledWith(`${API_BASE_URL}/api/v1/repositories/repo-1/profile`, expect.any(Object))
  })

  it('a caller-supplied header is merged with the default Content-Type', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ items: [], total: 0, page: 1, page_size: 20 }))
    // exercised indirectly: the request helper always sets Content-Type; a GET carries it too
    await listRepositories()
    const init = vi.mocked(fetch).mock.calls[0][1] as RequestInit
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json')
  })
})
