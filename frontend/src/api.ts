import type {
  AnalysisRun,
  ApiErrorBody,
  Branch,
  IngestRepositoryResponse,
  PaginatedRepositories,
  Repository,
} from './types'

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export class ApiError extends Error {
  code: string

  constructor(code: string, message: string) {
    super(message)
    this.code = code
    this.name = 'ApiError'
  }
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })

  if (!response.ok) {
    let body: ApiErrorBody | null = null
    try {
      body = (await response.json()) as ApiErrorBody
    } catch {
      // Response body wasn't JSON (e.g. a network-level failure surfaced
      // by a proxy) -- fall through to the generic error below.
    }
    if (body?.error) {
      throw new ApiError(body.error.code, body.error.message)
    }
    throw new ApiError('UNKNOWN_ERROR', `Request failed with status ${response.status}`)
  }

  return (await response.json()) as T
}

export function createRepository(sourceUrl: string, branch: string | null): Promise<IngestRepositoryResponse> {
  return apiFetch<IngestRepositoryResponse>('/api/v1/repositories', {
    method: 'POST',
    body: JSON.stringify({ source_url: sourceUrl, branch }),
  })
}

export function refreshRepository(
  repositoryId: string,
  branch: string | null,
): Promise<IngestRepositoryResponse> {
  return apiFetch<IngestRepositoryResponse>(`/api/v1/repositories/${repositoryId}/refresh`, {
    method: 'POST',
    body: JSON.stringify({ branch }),
  })
}

export function getAnalysisRun(runId: number): Promise<AnalysisRun> {
  return apiFetch<AnalysisRun>(`/api/v1/analysis-runs/${runId}`)
}

export function getRepository(repositoryId: string): Promise<Repository> {
  return apiFetch<Repository>(`/api/v1/repositories/${repositoryId}`)
}

export function listBranches(repositoryId: string): Promise<Branch[]> {
  return apiFetch<Branch[]>(`/api/v1/repositories/${repositoryId}/branches`)
}

export function listRepositories(limit = 20, offset = 0): Promise<PaginatedRepositories> {
  return apiFetch<PaginatedRepositories>(`/api/v1/repositories?limit=${limit}&offset=${offset}`)
}
