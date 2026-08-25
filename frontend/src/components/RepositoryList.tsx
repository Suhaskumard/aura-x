import { useEffect, useState } from 'react'
import { ApiError, listRepositories } from '../api'
import type { RepositorySummary } from '../api'
import StatusBadge from './StatusBadge'

interface Props {
  onSelect: (repositoryId: string) => void
  refreshToken: number
}

export default function RepositoryList({ onSelect, refreshToken }: Props) {
  const [repositories, setRepositories] = useState<RepositorySummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    listRepositories(1, 50)
      .then((page) => {
        if (!cancelled) setRepositories(page.items)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Could not load repositories.')
      })
    return () => {
      cancelled = true
    }
  }, [refreshToken])

  if (error) {
    return <p className="error-text">{error}</p>
  }

  if (repositories === null) {
    return <p className="muted">Loading repositories…</p>
  }

  if (repositories.length === 0) {
    return <p className="muted">No repositories analyzed yet -- paste a URL below to start.</p>
  }

  return (
    <ul className="repository-cards">
      {repositories.map((repo) => (
        <li key={repo.id}>
          <button type="button" className="repository-card" onClick={() => onSelect(repo.id)}>
            <div className="repository-card-title">
              <span>
                {repo.owner}/{repo.name}
              </span>
              <StatusBadge status={repo.latest_status} />
            </div>
            {repo.description && <p className="muted">{repo.description}</p>}
            <div className="repository-card-meta">
              {repo.primary_language && <span>{repo.primary_language}</span>}
              <span>★ {repo.stargazers_count}</span>
              <span>⑂ {repo.forks_count}</span>
            </div>
          </button>
        </li>
      ))}
    </ul>
  )
}
