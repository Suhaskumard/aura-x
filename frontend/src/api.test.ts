import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, createRepository, getAnalysisRun } from './api'

const originalFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = originalFetch
  vi.restoreAllMocks()
})

describe('createRepository', () => {
  it('parses a successful response', async () => {
    const mockResponse = {
      repository: { id: '1', owner: 'octocat', name: 'hello-world' },
      analysis_run: { id: 42, status: 'FETCHING_METADATA' },
    }
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockResponse,
    }) as unknown as typeof fetch

    const result = await createRepository('https://github.com/octocat/hello-world', null)
    expect(result.analysis_run.id).toBe(42)
    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/repositories'),
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ source_url: 'https://github.com/octocat/hello-world', branch: null }),
      }),
    )
  })

  it('throws ApiError with the structured error body on failure', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 400,
      json: async () => ({ error: { code: 'INVALID_REPOSITORY_URL', message: 'bad url' } }),
    }) as unknown as typeof fetch

    await expect(createRepository('not a url', null)).rejects.toMatchObject({
      code: 'INVALID_REPOSITORY_URL',
      message: 'bad url',
    })
  })

  it('falls back to a generic ApiError when the error body is not JSON', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 502,
      json: async () => {
        throw new Error('not json')
      },
    }) as unknown as typeof fetch

    await expect(createRepository('https://github.com/a/b', null)).rejects.toBeInstanceOf(ApiError)
  })
})

describe('getAnalysisRun', () => {
  it('requests the correct URL', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: 7, status: 'READY' }),
    }) as unknown as typeof fetch

    const result = await getAnalysisRun(7)
    expect(result.status).toBe('READY')
    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/analysis-runs/7'),
      expect.anything(),
    )
  })
})
