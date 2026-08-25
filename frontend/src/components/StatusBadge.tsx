import type { IngestionStatus } from '../api'

const LABELS: Record<IngestionStatus, string> = {
  QUEUED: 'Queued',
  VALIDATING: 'Validating',
  FETCHING: 'Fetching',
  CLONING: 'Cloning',
  ANALYZING: 'Analyzing',
  READY: 'Ready',
  FAILED: 'Failed',
}

export default function StatusBadge({ status }: { status: IngestionStatus | null }) {
  if (!status) {
    return <span className="badge badge-unknown">Unknown</span>
  }
  const variant =
    status === 'READY' ? 'success' : status === 'FAILED' ? 'danger' : 'progress'
  return <span className={`badge badge-${variant}`}>{LABELS[status]}</span>
}
