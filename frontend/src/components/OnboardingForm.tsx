import { useState } from 'react'
import type { FormEvent } from 'react'

interface OnboardingFormProps {
  onSubmit: (sourceUrl: string, branch: string | null) => void
  submitting: boolean
  errorMessage: string | null
}

export function OnboardingForm({ onSubmit, submitting, errorMessage }: OnboardingFormProps) {
  const [sourceUrl, setSourceUrl] = useState('')
  const [branch, setBranch] = useState('')

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!sourceUrl.trim()) return
    onSubmit(sourceUrl.trim(), branch.trim() ? branch.trim() : null)
  }

  return (
    <form className="onboarding-form" onSubmit={handleSubmit}>
      <label className="field">
        <span>GitHub repository URL</span>
        <input
          type="text"
          value={sourceUrl}
          onChange={(e) => setSourceUrl(e.target.value)}
          placeholder="https://github.com/owner/repo"
          disabled={submitting}
          required
        />
      </label>

      <label className="field">
        <span>Branch (optional -- default branch is used if left blank)</span>
        <input
          type="text"
          value={branch}
          onChange={(e) => setBranch(e.target.value)}
          placeholder="main"
          disabled={submitting}
        />
      </label>

      {errorMessage && <p className="error-text">{errorMessage}</p>}

      <button type="submit" disabled={submitting}>
        {submitting ? 'Starting ingestion…' : 'Analyze repository'}
      </button>
    </form>
  )
}
