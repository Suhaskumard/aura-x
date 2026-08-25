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

      {error && <p className="error-text">Lost contact with the backend: {error}. Retrying…</p>}

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
            <li key={stage} className={`stage stage-${state}`}>
              <span className="stage-dot" aria-hidden="true" />
              <span className="stage-label">{stage[0] + stage.slice(1).toLowerCase()}</span>
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
