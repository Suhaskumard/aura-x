import { useEffect, useState } from 'react'
import {
  ApiError,
  getRepositoryBranches,
  getRepositoryProfile,
  refreshRepository,
} from '../api'
import type { BranchOut, RepositoryProfile } from '../api'
import StatusBadge from './StatusBadge'

interface Props {
  repositoryId: string
  onRefreshStarted: (analysisRunId: string) => void
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export default function RepositoryProfileView({ repositoryId, onRefreshStarted }: Props) {
  const [profile, setProfile] = useState<RepositoryProfile | null>(null)
  const [branches, setBranches] = useState<BranchOut[]>([])
  const [selectedBranch, setSelectedBranch] = useState('')
  const [loadError, setLoadError] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [refreshError, setRefreshError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoadError(null)
    Promise.all([getRepositoryProfile(repositoryId), getRepositoryBranches(repositoryId)])
      .then(([profileResponse, branchList]) => {
        if (cancelled) return
        setProfile(profileResponse.profile)
        setBranches(branchList)
        setSelectedBranch(profileResponse.profile.selected_branch ?? '')
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setLoadError(err instanceof ApiError ? err.message : 'Could not load the repository profile.')
      })
    return () => {
      cancelled = true
    }
  }, [repositoryId])

  async function handleReanalyze() {
    setRefreshing(true)
    setRefreshError(null)
    try {
      const result = await refreshRepository(repositoryId, selectedBranch || undefined)
      onRefreshStarted(result.analysis_run_id)
    } catch (err) {
      setRefreshError(err instanceof ApiError ? err.message : 'Could not start re-analysis.')
      setRefreshing(false)
    }
  }

  if (loadError) {
    return <p className="error-text">{loadError}</p>
  }

  if (!profile) {
    return <p className="muted">Loading repository profile…</p>
  }

  const languageEntries = Object.entries(profile.languages).sort(([, a], [, b]) => b - a)
  const totalLanguageBytes = languageEntries.reduce((sum, [, bytes]) => sum + bytes, 0)

  return (
    <div className="profile">
      <div className="profile-header">
        <div>
          <h2>
            {profile.owner}/{profile.repository_name}
          </h2>
          {profile.description && <p className="muted">{profile.description}</p>}
        </div>
        {/* This view only renders once a run has reached READY -- see App.tsx */}
        <StatusBadge status="READY" />
      </div>

      <dl className="profile-facts">
        <div>
          <dt>Branch</dt>
          <dd>{profile.selected_branch ?? '—'}</dd>
        </div>
        <div>
          <dt>Commit</dt>
          <dd>
            <code>{profile.commit_sha ? profile.commit_sha.slice(0, 12) : '—'}</code>
          </dd>
        </div>
        <div>
          <dt>Visibility</dt>
          <dd>{profile.visibility ?? '—'}</dd>
        </div>
        <div>
          <dt>Stars</dt>
          <dd>{profile.stargazers_count ?? '—'}</dd>
        </div>
        <div>
          <dt>Forks</dt>
          <dd>{profile.forks_count ?? '—'}</dd>
        </div>
        <div>
          <dt>Files scanned</dt>
          <dd>{profile.file_inventory.total_files.toLocaleString()}</dd>
        </div>
        <div>
          <dt>Total size</dt>
          <dd>{formatBytes(profile.file_inventory.total_size_bytes)}</dd>
        </div>
        <div>
          <dt>Commits analyzed</dt>
          <dd>{profile.git_history_summary.commit_count}</dd>
        </div>
      </dl>

      <section>
        <h3>Languages</h3>
        {languageEntries.length === 0 ? (
          <p className="muted">No languages detected.</p>
        ) : (
          <ul className="language-bars">
            {languageEntries.map(([language, bytes]) => {
              const pct = totalLanguageBytes > 0 ? (100 * bytes) / totalLanguageBytes : 0
              return (
                <li key={language}>
                  <span className="language-name">{language}</span>
                  <span className="language-bar-track">
                    <span className="language-bar-fill" style={{ width: `${pct}%` }} />
                  </span>
                  <span className="language-pct">{pct.toFixed(1)}%</span>
                </li>
              )
            })}
          </ul>
        )}
      </section>

      <section>
        <h3>Test frameworks</h3>
        {profile.test_frameworks.length === 0 ? (
          <p className="muted">No test frameworks detected.</p>
        ) : (
          <ul className="pill-list">
            {profile.test_frameworks.map((framework) => (
              <li key={framework} className="pill">
                {framework}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h3>Dependencies ({profile.dependencies.length})</h3>
        {profile.dependencies.length === 0 ? (
          <p className="muted">No dependency manifests detected.</p>
        ) : (
          <ul className="pill-list">
            {profile.dependencies.slice(0, 24).map((dependency) => (
              <li key={dependency} className="pill pill-muted">
                {dependency}
              </li>
            ))}
            {profile.dependencies.length > 24 && (
              <li className="pill pill-muted">+{profile.dependencies.length - 24} more</li>
            )}
          </ul>
        )}
      </section>

      <section className="reanalyze">
        <h3>Re-analyze</h3>
        <p className="muted">Pick a different branch and re-run ingestion against it.</p>
        <div className="reanalyze-controls">
          <select
            value={selectedBranch}
            onChange={(event) => setSelectedBranch(event.target.value)}
            disabled={refreshing || branches.length === 0}
          >
            {branches.map((branch) => (
              <option key={branch.name} value={branch.name}>
                {branch.name}
                {branch.is_default ? ' (default)' : ''}
              </option>
            ))}
          </select>
          <button type="button" onClick={handleReanalyze} disabled={refreshing}>
            {refreshing ? 'Starting…' : 'Re-analyze this branch'}
          </button>
        </div>
        {refreshError && <p className="error-text">{refreshError}</p>}
      </section>
    </div>
  )
}
