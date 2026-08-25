import { useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError, ingestRepository } from '../api'

interface Props {
  onStarted: (repositoryId: string, analysisRunId: string) => void
}

export default function OnboardingForm({ onStarted }: Props) {
  const [url, setUrl] = useState('')
  const [branch, setBranch] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [validationError, setValidationError] = useState<string | null>(null)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setValidationError(null)

    if (!url.trim()) {
      setValidationError('Enter a GitHub repository URL, e.g. https://github.com/octocat/Hello-World')
      return
    }

    setSubmitting(true)
    try {
      const result = await ingestRepository(url.trim(), branch.trim() || undefined)
      onStarted(result.repository_id, result.analysis_run_id)
      setUrl('')
      setBranch('')
    } catch (err) {
      if (err instanceof ApiError) {
        setValidationError(err.message)
      } else {
        setValidationError('Could not start analysis. Please try again.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form className="onboarding-form" onSubmit={handleSubmit}>
      <h2>Analyze a repository</h2>
      <p className="muted">
        Paste a public GitHub repository URL to start real ingestion -- metadata, branches,
        a shallow clone, and a full scan for languages, test frameworks, and evolution signals.
      </p>

      <label htmlFor="repository-url">Repository URL</label>
      <input
        id="repository-url"
        type="text"
        placeholder="https://github.com/owner/repository"
        value={url}
        onChange={(event) => setUrl(event.target.value)}
        disabled={submitting}
        autoComplete="off"
      />

      <label htmlFor="repository-branch">Branch (optional)</label>
      <input
        id="repository-branch"
        type="text"
        placeholder="defaults to the repository's default branch"
        value={branch}
        onChange={(event) => setBranch(event.target.value)}
        disabled={submitting}
        autoComplete="off"
      />

      {validationError && (
        <p className="error-text" role="alert">
          {validationError}
        </p>
      )}

      <button type="submit" disabled={submitting}>
        {submitting ? 'Starting…' : 'Analyze repository'}
      </button>
    </form>
  )
}
