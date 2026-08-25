import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AnalysisRunStatus } from '../api'
import IngestionProgress from './IngestionProgress'

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api')
  return { ...actual, getAnalysisRunStatus: vi.fn() }
})

import { getAnalysisRunStatus } from '../api'

function run(overrides: Partial<AnalysisRunStatus> = {}): AnalysisRunStatus {
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
    ...overrides,
  }
}

async function flush() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0)
  })
}

describe('IngestionProgress', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.mocked(getAnalysisRunStatus).mockReset()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('highlights the current stage and marks earlier stages done', async () => {
    vi.mocked(getAnalysisRunStatus).mockResolvedValue(run({ status: 'CLONING' }))
    render(
      <IngestionProgress repositoryId="repo-1" analysisRunId="run-1" onReady={vi.fn()} onFailed={vi.fn()} />,
    )
    await flush()

    const stages = screen.getAllByRole('listitem')
    expect(stages[0]).toHaveClass('stage-done') // QUEUED
    expect(stages[1]).toHaveClass('stage-done') // VALIDATING
    expect(stages[2]).toHaveClass('stage-done') // FETCHING
    expect(stages[3]).toHaveClass('stage-active') // CLONING
    expect(stages[4]).toHaveClass('stage-pending') // ANALYZING
    expect(stages[5]).toHaveClass('stage-pending') // READY
  })

  it('calls onReady exactly once when status reaches READY', async () => {
    vi.mocked(getAnalysisRunStatus)
      .mockResolvedValueOnce(run({ status: 'ANALYZING' }))
      .mockResolvedValueOnce(run({ status: 'READY' }))
    const onReady = vi.fn()
    render(
      <IngestionProgress repositoryId="repo-1" analysisRunId="run-1" onReady={onReady} onFailed={vi.fn()} />,
    )
    await flush()
    expect(onReady).not.toHaveBeenCalled()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500)
    })
    expect(onReady).toHaveBeenCalledTimes(1)

    // Further time passing must not re-fire onReady (polling has stopped).
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000)
    })
    expect(onReady).toHaveBeenCalledTimes(1)
  })

  it('calls onFailed with the error code/message exactly once on FAILED', async () => {
    vi.mocked(getAnalysisRunStatus).mockResolvedValue(
      run({ status: 'FAILED', error_code: 'CLONE_TIMEOUT', error_message: 'Clone took too long' }),
    )
    const onFailed = vi.fn()
    render(
      <IngestionProgress repositoryId="repo-1" analysisRunId="run-1" onReady={vi.fn()} onFailed={onFailed} />,
    )
    await flush()
    expect(onFailed).toHaveBeenCalledTimes(1)
    expect(onFailed).toHaveBeenCalledWith('CLONE_TIMEOUT', 'Clone took too long')

    const stages = screen.getAllByRole('listitem')
    expect(stages.every((s) => s.className.includes('stage-stalled'))).toBe(true)
  })

  it('shows a "lost contact" message on poll error but keeps retrying', async () => {
    vi.mocked(getAnalysisRunStatus).mockRejectedValue(new Error('network down'))
    render(
      <IngestionProgress repositoryId="repo-1" analysisRunId="run-1" onReady={vi.fn()} onFailed={vi.fn()} />,
    )
    await flush()
    expect(screen.getByText(/lost contact with the backend/i)).toHaveTextContent('network down')
  })

  it('displays the branch name once it is known', async () => {
    vi.mocked(getAnalysisRunStatus).mockResolvedValue(run({ status: 'CLONING', branch_name: 'feature/x' }))
    render(
      <IngestionProgress repositoryId="repo-1" analysisRunId="run-1" onReady={vi.fn()} onFailed={vi.fn()} />,
    )
    await flush()
    expect(screen.getByText('feature/x')).toBeInTheDocument()
  })

  it('restarts polling from QUEUED when analysisRunId changes', async () => {
    vi.mocked(getAnalysisRunStatus).mockResolvedValue(run({ status: 'READY' }))
    const { rerender } = render(
      <IngestionProgress repositoryId="repo-1" analysisRunId="run-1" onReady={vi.fn()} onFailed={vi.fn()} />,
    )
    await flush()
    expect(getAnalysisRunStatus).toHaveBeenCalledWith('repo-1', 'run-1')

    vi.mocked(getAnalysisRunStatus).mockResolvedValue(run({ status: 'QUEUED' }))
    rerender(
      <IngestionProgress repositoryId="repo-1" analysisRunId="run-2" onReady={vi.fn()} onFailed={vi.fn()} />,
    )
    await flush()
    expect(getAnalysisRunStatus).toHaveBeenCalledWith('repo-1', 'run-2')
  })
})
