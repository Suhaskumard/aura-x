import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AnalysisRunStatus } from '../api'
import IngestionProgress from './IngestionProgress'

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api')
  return { ...actual, getAnalysisRunStatus: vi.fn() }
})
import { getAnalysisRunStatus } from '../api'

function run(over: Partial<AnalysisRunStatus> = {}): AnalysisRunStatus {
  return {
    id: 'run-1',
    repository_id: 'repo-1',
    status: 'QUEUED',
    branch_name: null,
    commit_sha: null,
    error_code: null,
    error_message: null,
    started_at: '2026-01-01T00:00:00Z',
    completed_at: null,
    ...over,
  }
}
const flush = () => act(async () => void (await vi.advanceTimersByTimeAsync(0)))

describe('IngestionProgress - status-line branches not covered elsewhere', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.mocked(getAnalysisRunStatus).mockReset()
  })
  afterEach(() => vi.useRealTimers())

  it('shows "Starting ingestion…" before the first poll resolves', () => {
    vi.mocked(getAnalysisRunStatus).mockReturnValue(new Promise(() => {}))
    render(<IngestionProgress repositoryId="repo-1" analysisRunId="run-1" onReady={vi.fn()} onFailed={vi.fn()} />)
    expect(screen.getByRole('status')).toHaveTextContent(/starting ingestion/i)
  })

  it('announces "Ingestion complete." once the run reaches READY', async () => {
    vi.mocked(getAnalysisRunStatus).mockResolvedValue(run({ status: 'READY' }))
    const onReady = vi.fn()
    render(<IngestionProgress repositoryId="repo-1" analysisRunId="run-1" onReady={onReady} onFailed={vi.fn()} />)
    await flush()
    expect(screen.getByText('Ingestion complete.')).toBeInTheDocument()
    expect(onReady).toHaveBeenCalledTimes(1)
  })

  it('does not keep polling after a terminal READY response', async () => {
    vi.mocked(getAnalysisRunStatus).mockResolvedValue(run({ status: 'READY' }))
    render(<IngestionProgress repositoryId="repo-1" analysisRunId="run-1" onReady={vi.fn()} onFailed={vi.fn()} />)
    await flush()
    const calls = vi.mocked(getAnalysisRunStatus).mock.calls.length
    await act(async () => void (await vi.advanceTimersByTimeAsync(6000)))
    expect(vi.mocked(getAnalysisRunStatus).mock.calls.length).toBe(calls)
  })
})
