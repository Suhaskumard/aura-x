import { useState } from 'react'
import { ApiError, createRepository, getRepository } from './api'
import { IngestionProgress } from './components/IngestionProgress'
import { OnboardingForm } from './components/OnboardingForm'
import { RepositoryProfile } from './components/RepositoryProfile'
import type { AnalysisRun, Repository } from './types'
import './App.css'

type ViewState =
  | { kind: 'idle' }
  | { kind: 'submitting' }
  | { kind: 'polling'; runId: number }
  | { kind: 'ready'; repository: Repository; run: AnalysisRun }
  | { kind: 'failed'; run: AnalysisRun }
  | { kind: 'submit-error'; message: string }

function App() {
  const [state, setState] = useState<ViewState>({ kind: 'idle' })

  async function handleSubmit(sourceUrl: string, branch: string | null) {
    setState({ kind: 'submitting' })
    try {
      const result = await createRepository(sourceUrl, branch)
      setState({ kind: 'polling', runId: result.analysis_run.id })
    } catch (err) {
      const message = err instanceof ApiError ? err.message : 'Failed to start ingestion'
      setState({ kind: 'submit-error', message })
    }
  }

  async function handleSettled(run: AnalysisRun) {
    if (run.status === 'FAILED') {
      setState({ kind: 'failed', run })
      return
    }
    try {
      const repository = await getRepository(run.repository_id)
      setState({ kind: 'ready', repository, run })
    } catch (err) {
      const message = err instanceof ApiError ? err.message : 'Failed to load repository profile'
      setState({ kind: 'submit-error', message })
    }
  }

  function handleRefreshStarted(run: AnalysisRun) {
    setState({ kind: 'polling', runId: run.id })
  }

  function handleStartOver() {
    setState({ kind: 'idle' })
  }

  return (
    <main className="app-shell">
      <h1>AURA-X</h1>
      <p className="tagline">Autonomous Unified Reliability &amp; Evolution Analyzer</p>

      {(state.kind === 'idle' || state.kind === 'submitting' || state.kind === 'submit-error') && (
        <OnboardingForm
          onSubmit={handleSubmit}
          submitting={state.kind === 'submitting'}
          errorMessage={state.kind === 'submit-error' ? state.message : null}
        />
      )}

      {state.kind === 'polling' && (
        <IngestionProgress runId={state.runId} onSettled={handleSettled} />
      )}

      {state.kind === 'failed' && (
        <div className="run-failed-panel">
          <h2>Ingestion failed</h2>
          <p>{state.run.last_error?.message ?? 'Unknown error'}</p>
          {state.run.last_error && <p className="error-code">{state.run.last_error.code}</p>}
          <button onClick={handleStartOver}>Try another repository</button>
        </div>
      )}

      {state.kind === 'ready' && (
        <>
          <RepositoryProfile
            repository={state.repository}
            commitSha={state.run.commit_sha}
            onRefreshStarted={handleRefreshStarted}
          />
          <button className="start-over" onClick={handleStartOver}>
            Analyze another repository
          </button>
        </>
      )}
    </main>
  )
}

export default App
