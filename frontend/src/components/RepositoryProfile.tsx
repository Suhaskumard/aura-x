import { useEffect, useState } from 'react'
import { listBranches, refreshRepository } from '../api'
import type { AnalysisRun, Branch, Repository } from '../types'

interface RepositoryProfileProps {
  repository: Repository
  commitSha: string | null
  onRefreshStarted: (run: AnalysisRun) => void
}

export function RepositoryProfile({ repository, commitSha, onRefreshStarted }: RepositoryProfileProps) {
  const [branches, setBranches] = useState<Branch[] | null>(null)
  const [branchesError, setBranchesError] = useState<string | null>(null)
  const [switching, setSwitching] = useState(false)
  const [switchError, setSwitchError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    listBranches(repository.id)
      .then((result) => {
        if (!cancelled) setBranches(result)
      })
      .catch((err: Error) => {
        if (!cancelled) setBranchesError(err.message)
      })
    return () => {
      cancelled = true
    }
  }, [repository.id])

  async function handleSwitchBranch(branchName: string) {
    setSwitching(true)
    setSwitchError(null)
    try {
      const result = await refreshRepository(repository.id, branchName)
      onRefreshStarted(result.analysis_run)
    } catch (err) {
      setSwitchError(err instanceof Error ? err.message : 'Failed to switch branch')
    } finally {
      setSwitching(false)
    }
  }

  return (
    <div className="repository-profile">
      <h2>
        {repository.owner}/{repository.name}
      </h2>
      {repository.description && <p className="description">{repository.description}</p>}

      <dl className="profile-facts">
        <div>
          <dt>Visibility</dt>
          <dd>{repository.visibility}</dd>
        </div>
        <div>
          <dt>Primary language</dt>
          <dd>{repository.primary_language ?? 'unknown'}</dd>
        </div>
        <div>
          <dt>Default branch</dt>
          <dd>{repository.default_branch ?? 'unknown'}</dd>
        </div>
        <div>
          <dt>Stars</dt>
          <dd>{repository.stargazers_count}</dd>
        </div>
        <div>
          <dt>Forks</dt>
          <dd>{repository.forks_count}</dd>
        </div>
        <div>
          <dt>Commit SHA</dt>
          <dd>
            <code>{commitSha ?? 'unknown'}</code>
          </dd>
        </div>
      </dl>

      <h3>Branches</h3>
      {branchesError && <p className="error-text">{branchesError}</p>}
      {!branchesError && !branches && <p>Loading branches…</p>}
      {branches && (
        <ul className="branch-list">
          {branches.map((branch) => (
            <li key={branch.id}>
              <span>
                {branch.name} {branch.is_default && <em>(default)</em>}
              </span>
              <button disabled={switching} onClick={() => handleSwitchBranch(branch.name)}>
                Analyze this branch
              </button>
            </li>
          ))}
        </ul>
      )}
      {switchError && <p className="error-text">{switchError}</p>}
    </div>
  )
}
