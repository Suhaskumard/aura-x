import { useEffect } from 'react'
import { getAnalysisRunStatus } from '../api'
import type { IngestionStatus } from '../api'
import { usePolling } from '../usePolling'
import StatusBadge from './StatusBadge'

// The real, ordered pipeline stages (see backend/app/api/v1/status_mapping.py).
// A stage lights up only once the polled status actually reports it --
// nothing here is a timer or a simulated animation.
const STAGES: IngestionStatus[] = ['QUEUED', 'VALIDATING', 'FETCHING', 'CLONING', 'ANALYZING', 'READY']

function stageIndex(status: IngestionStatus | undefined): number {
  if (!status) return -1
  if (status === 'FAILED') return -1
  return STAGES.indexOf(status)
}

function label(stage: IngestionStatus): string {
  return stage[0] + stage.slice(1).toLowerCase()
}

const STATE_WORDS: Record<string, string> = {
  done: 'completed',
  active: 'in progress',
  pending: 'not started',
  stalled: 'did not complete',
}

interface Props {
  repositoryId: string
  analysisRunId: string
  onReady: () => void
  onFailed: (errorCode: string | null, errorMessage: string | null) => void
}

export default function IngestionProgress({ repositoryId, analysisRunId, onReady, onFailed }: Props) {
  const { value: run, error } = usePolling(
    () => getAnalysisRunStatus(repositoryId, analysisRunId),
    1500,
    (result) => result.status === 'READY' || result.status === 'FAILED',
    [repositoryId, analysisRunId],
  )

  const current = stageIndex(run?.status)
  const failed = run?.status === 'FAILED'

  useEffect(() => {
    if (run?.status === 'READY') {
      onReady()
    } else if (run?.status === 'FAILED') {
      onFailed(run.error_code, run.error_message)
    }
    // onReady/onFailed are expected to be stable-enough callbacks from the
    // parent; re-firing only when the polled run's status actually changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.status])

  return (
    <div className="ingestion-progress">
      <div className="ingestion-progress-header">
        <h2>Analyzing repository</h2>
        <StatusBadge status={run?.status ?? null} />
      </div>

      {error && (
        <p className="error-text" role="status">
          Lost contact with the backend: {error}. Retrying…
        </p>
      )}

      <p className="muted" role="status">
        {failed
          ? 'Ingestion failed before it could finish.'
          : run?.status === 'READY'
            ? 'Ingestion complete.'
            : run?.status
              ? `Current stage: ${label(run.status)} — step ${current + 1} of ${STAGES.length}.`
              : 'Starting ingestion…'}
      </p>

      <ol className="stage-list">
        {STAGES.map((stage, index) => {
          const state = failed
            ? 'stalled'
            : index < current
              ? 'done'
              : index === current
                ? 'active'
                : 'pending'
          return (
            <li
              key={stage}
              className={`stage stage-${state}`}
              aria-current={state === 'active' ? 'step' : undefined}
              aria-label={`${label(stage)} — ${STATE_WORDS[state]}`}
            >
              <span className="stage-dot" aria-hidden="true" />
              <span className="stage-label">{label(stage)}</span>
            </li>
          )
        })}
      </ol>

      {run?.branch_name && (
        <p className="muted">
          Branch: <code>{run.branch_name}</code>
        </p>
      )}
    </div>
  )
}
