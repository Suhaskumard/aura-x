import { useRef, useState } from 'react'
import './App.css'
import { ApiError, getRepository, refreshRepository } from './api'
import IngestionProgress from './components/IngestionProgress'
import OnboardingForm from './components/OnboardingForm'
import RepositoryList from './components/RepositoryList'
import RepositoryProfileView from './components/RepositoryProfileView'

type View =
  | { kind: 'list' }
  | { kind: 'progress'; repositoryId: string; analysisRunId: string }
  | { kind: 'profile'; repositoryId: string }
  | { kind: 'failed'; repositoryId: string; errorCode: string | null; errorMessage: string | null }

function App() {
  const [view, setView] = useState<View>({ kind: 'list' })
  const [refreshToken, setRefreshToken] = useState(0)
  const [selectError, setSelectError] = useState<string | null>(null)
  // Monotonic id for the most recent repository-open request. A slower
  // earlier getRepository() must not win a race against a later click (or
  // against the user returning to the list), so every resolution checks
  // it is still the newest before it navigates.
  const selectSeqRef = useRef(0)

  function backToList() {
    selectSeqRef.current += 1
    setView({ kind: 'list' })
    setRefreshToken((token) => token + 1)
  }

  async function handleSelectRepository(repositoryId: string) {
    const seq = (selectSeqRef.current += 1)
    setSelectError(null)
    try {
      const detail = await getRepository(repositoryId)
      if (seq !== selectSeqRef.current) return
      const run = detail.latest_analysis_run
      if (!run || run.status === 'READY') {
        setView({ kind: 'profile', repositoryId })
      } else if (run.status === 'FAILED') {
        setView({
          kind: 'failed',
          repositoryId,
          errorCode: run.error_code,
          errorMessage: run.error_message,
        })
      } else {
        setView({ kind: 'progress', repositoryId, analysisRunId: run.id })
      }
    } catch (err) {
      if (seq !== selectSeqRef.current) return
      setSelectError(err instanceof ApiError ? err.message : 'Could not open this repository.')
    }
  }

  return (
    <main className="app">
      <header className="app-header">
        <h1>AURA-X</h1>
        <p className="muted">Autonomous Unified Reliability &amp; Evolution Analyzer</p>
      </header>

      {view.kind !== 'list' && (
        <button type="button" className="link-button" onClick={backToList}>
          ← Back to repositories
        </button>
      )}

      {view.kind === 'list' && (
        <>
          <section>
            <h2>Repositories</h2>
            {selectError && <p className="error-text">{selectError}</p>}
            <RepositoryList onSelect={handleSelectRepository} refreshToken={refreshToken} />
          </section>
          <OnboardingForm
            onStarted={(repositoryId, analysisRunId) =>
              setView({ kind: 'progress', repositoryId, analysisRunId })
            }
          />
        </>
      )}

      {view.kind === 'progress' && (
        <IngestionProgress
          repositoryId={view.repositoryId}
          analysisRunId={view.analysisRunId}
          onReady={() => setView({ kind: 'profile', repositoryId: view.repositoryId })}
          onFailed={(errorCode, errorMessage) =>
            setView({ kind: 'failed', repositoryId: view.repositoryId, errorCode, errorMessage })
          }
        />
      )}

      {view.kind === 'profile' && (
        <RepositoryProfileView
          repositoryId={view.repositoryId}
          onRefreshStarted={(analysisRunId) =>
            setView({ kind: 'progress', repositoryId: view.repositoryId, analysisRunId })
          }
        />
      )}

      {view.kind === 'failed' && (
        <FailureView
          errorCode={view.errorCode}
          errorMessage={view.errorMessage}
          onRetry={async () => {
            const result = await refreshRepository(view.repositoryId)
            setView({ kind: 'progress', repositoryId: view.repositoryId, analysisRunId: result.analysis_run_id })
          }}
        />
      )}
    </main>
  )
}

function FailureView({
  errorCode,
  errorMessage,
  onRetry,
}: {
  errorCode: string | null
  errorMessage: string | null
  onRetry: () => Promise<void>
}) {
  const [retrying, setRetrying] = useState(false)
  const [retryError, setRetryError] = useState<string | null>(null)

  async function handleRetry() {
    setRetrying(true)
    setRetryError(null)
    try {
      await onRetry()
    } catch (err) {
      setRetryError(err instanceof ApiError ? err.message : 'Could not retry analysis.')
      setRetrying(false)
    }
  }

  return (
    <div className="failure">
      <h2>Analysis failed</h2>
      <p className="error-text">
        {errorCode && <code>{errorCode}</code>}
        {errorCode && errorMessage ? ' — ' : ''}
        {errorMessage ?? 'The ingestion run did not complete successfully.'}
      </p>
      <button type="button" onClick={handleRetry} disabled={retrying}>
        {retrying ? 'Retrying…' : 'Retry analysis'}
      </button>
      {retryError && <p className="error-text">{retryError}</p>}
    </div>
  )
}

export default App
