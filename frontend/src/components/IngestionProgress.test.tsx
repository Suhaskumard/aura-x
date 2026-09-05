import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { IngestionProgress } from './IngestionProgress'
import type { AnalysisRun } from '../types'

const originalFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = originalFetch
  vi.restoreAllMocks()
})

function mockRun(overrides: Partial<AnalysisRun>): AnalysisRun {
  return {
    id: 1,
    repository_id: 'abc',
    branch_id: null,
    requested_branch: null,
    commit_sha: null,
    status: 'PENDING',
    last_error: null,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    ...overrides,
  }
}

describe('IngestionProgress', () => {
  it('polls until READY and calls onSettled with the final run', async () => {
    const responses: AnalysisRun[] = [
      mockRun({ status: 'PENDING' }),
      mockRun({ status: 'CLONING' }),
      mockRun({ status: 'READY', commit_sha: 'abc123' }),
    ]
    let callIndex = 0
    globalThis.fetch = vi.fn().mockImplementation(() => {
      const body = responses[Math.min(callIndex, responses.length - 1)]
      callIndex += 1
      return Promise.resolve({ ok: true, json: async () => body })
    }) as unknown as typeof fetch

    const onSettled = vi.fn()
    render(<IngestionProgress runId={1} onSettled={onSettled} />)

    await waitFor(() => expect(onSettled).toHaveBeenCalledWith(expect.objectContaining({ status: 'READY' })), {
      timeout: 10000,
      interval: 50,
    })
  })

  it('renders the structured error message when the run fails', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () =>
        mockRun({
          status: 'FAILED',
          last_error: { code: 'REPOSITORY_NOT_FOUND', message: 'Repository not found' },
        }),
    }) as unknown as typeof fetch

    render(<IngestionProgress runId={1} onSettled={vi.fn()} />)

    expect(await screen.findByText(/Repository not found/i)).toBeInTheDocument()
    expect(screen.getByText('REPOSITORY_NOT_FOUND')).toBeInTheDocument()
  })

  it('renders every real pipeline step, never a synthetic one', () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockRun({ status: 'SCANNING' }),
    }) as unknown as typeof fetch

    render(<IngestionProgress runId={1} onSettled={vi.fn()} />)

    for (const label of [
      'Queued',
      'Validating URL',
      'Fetching repository metadata',
      'Resolving branch',
      'Cloning repository',
      'Scanning files',
      'Ready',
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
  })
})
