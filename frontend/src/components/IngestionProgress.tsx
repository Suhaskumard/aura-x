import { useEffect, useRef, useState } from 'react'
import { getAnalysisRun } from '../api'
import { PIPELINE_STEPS } from '../types'
import type { AnalysisRun } from '../types'

const POLL_INTERVAL_MS = 1500

const STEP_LABELS: Record<string, string> = {
  PENDING: 'Queued',
  VALIDATING: 'Validating URL',
  FETCHING_METADATA: 'Fetching repository metadata',
  FETCHING_BRANCHES: 'Resolving branch',
  CLONING: 'Cloning repository',
  SCANNING: 'Scanning files',
  READY: 'Ready',
}

interface IngestionProgressProps {
  runId: number
  onSettled: (run: AnalysisRun) => void
}

/**
 * Polls GET /analysis-runs/{id} until the run reaches READY or FAILED.
 * Every rendered step is a real IngestionStatus value from PIPELINE_STEPS
 * -- there is no simulated/animated fake progress here.
 */
export function IngestionProgress({ runId, onSettled }: IngestionProgressProps) {
  const [run, setRun] = useState<AnalysisRun | null>(null)
  const [pollError, setPollError] = useState<string | null>(null)
  const onSettledRef = useRef(onSettled)
  onSettledRef.current = onSettled

  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined

    async function poll() {
      try {
        const latest = await getAnalysisRun(runId)
        if (cancelled) return
        setRun(latest)
        setPollError(null)

        if (latest.status === 'READY' || latest.status === 'FAILED') {
          onSettledRef.current(latest)
          return
        }
        timer = setTimeout(poll, POLL_INTERVAL_MS)
      } catch (err) {
        if (cancelled) return
        setPollError(err instanceof Error ? err.message : 'Failed to fetch ingestion status')
        timer = setTimeout(poll, POLL_INTERVAL_MS)
      }
    }

    void poll()
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [runId])

  const currentIndex = run ? PIPELINE_STEPS.indexOf(run.status) : -1

  return (
    <div className="ingestion-progress">
      <h2>Analyzing repository…</h2>
      {pollError && <p className="error-text">Polling error: {pollError} (retrying)</p>}

      <ol className="pipeline-steps">
        {PIPELINE_STEPS.map((step, index) => {
          const state =
            currentIndex < 0
              ? 'pending'
              : index < currentIndex
                ? 'done'
                : index === currentIndex
                  ? 'current'
                  : 'pending'
          return (
            <li key={step} className={`pipeline-step pipeline-step--${state}`}>
              {STEP_LABELS[step]}
            </li>
          )
        })}
      </ol>

      {run?.status === 'FAILED' && run.last_error && (
        <div className="run-failed">
          <p>
            <strong>Ingestion failed:</strong> {run.last_error.message}
          </p>
          <p className="error-code">{run.last_error.code}</p>
        </div>
      )}
    </div>
  )
}
