// Typed client for /api/v1/repositories (Phase 10-11 backend). Mirrors
// backend/app/api/v1/schemas.py exactly -- no field here is invented on
// the frontend side; everything rendered by the dashboard comes from one
// of these response shapes.

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

// Public ingestion status vocabulary -- see
// backend/app/api/v1/status_mapping.py. Every status field in every
// response below already carries one of these values.
export type IngestionStatus =
  | 'QUEUED'
  | 'VALIDATING'
  | 'FETCHING'
  | 'CLONING'
  | 'ANALYZING'
  | 'READY'
  | 'FAILED'

export class ApiError extends Error {
  code: string
  status: number
  constructor(code: string, message: string, status: number) {
    super(message)
    this.code = code
    this.status = status
  }
}

export interface IngestRepositoryResponse {
  repository_id: string
  provider: string
  source_url: string
  name: string
  owner: string
  selected_branch: string | null
  commit_sha: string | null
  status: IngestionStatus
  analysis_run_id: string
  error_code: string | null
  error_message: string | null
}

export interface AnalysisRunStatus {
  id: string
  repository_id: string
  status: IngestionStatus
  branch_name: string | null
  commit_sha: string | null
  error_code: string | null
  error_message: string | null
  started_at: string
  completed_at: string | null
}

export interface RepositorySummary {
  id: string
  provider: string
  owner: string
  name: string
  source_url: string
  default_branch: string | null
  description: string | null
  visibility: string | null
  primary_language: string | null
  stargazers_count: number
  forks_count: number
  latest_status: IngestionStatus | null
  updated_at: string
}

export interface PaginatedRepositories {
  items: RepositorySummary[]
  total: number
  page: number
  page_size: number
}

export interface LatestAnalysisRun {
  id: string
  status: IngestionStatus
  branch_name: string | null
  commit_sha: string | null
  error_code: string | null
  error_message: string | null
  started_at: string
  completed_at: string | null
}

export interface RepositoryDetail extends RepositorySummary {
  license_name: string | null
  topics: string[]
  open_issues_count: number
  latest_analysis_run: LatestAnalysisRun | null
}

export interface BranchOut {
  name: string
  head_commit_sha: string
  is_default: boolean
}

export interface RepositoryProfile {
  repository_id: string
  provider: string
  owner: string
  repository_name: string
  source_url: string
  selected_branch: string | null
  default_branch: string | null
  commit_sha: string | null
  status: string
  description: string | null
  visibility: string | null
  stargazers_count: number | null
  forks_count: number | null
  languages: Record<string, number>
  test_frameworks: string[]
  test_directories: string[]
  dependencies: string[]
  file_inventory: {
    total_files: number
    total_size_bytes: number
    by_category: Record<string, number>
  }
  git_history_summary: {
    commit_count: number
    most_recent_commit_at: string | null
  }
  updated_at: string
}

export interface RepositoryProfileResponse {
  repository_id: string
  analysis_run_id: string
  status: IngestionStatus
  profile: RepositoryProfile
  completed_at: string | null
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...init?.headers },
    })
  } catch {
    throw new ApiError('NETWORK_ERROR', `Could not reach the backend at ${API_BASE_URL}`, 0)
  }

  if (!response.ok) {
    let code = 'UNKNOWN_ERROR'
    let message = `Request failed with status ${response.status}`
    try {
      const body = (await response.json()) as { code?: string; message?: string }
      if (body.code) code = body.code
      if (body.message) message = body.message
    } catch {
      // response body wasn't JSON -- keep the generic message above
    }
    throw new ApiError(code, message, response.status)
  }

  return response.json() as Promise<T>
}

export function ingestRepository(repositoryUrl: string, branch?: string): Promise<IngestRepositoryResponse> {
  return request('/api/v1/repositories/github', {
    method: 'POST',
    body: JSON.stringify({ repository_url: repositoryUrl, branch: branch || null }),
  })
}

export function refreshRepository(repositoryId: string, branch?: string): Promise<IngestRepositoryResponse> {
  return request(`/api/v1/repositories/${repositoryId}/refresh`, {
    method: 'POST',
    body: JSON.stringify({ branch: branch || null }),
  })
}

export function getAnalysisRunStatus(repositoryId: string, runId: string): Promise<AnalysisRunStatus> {
  return request(`/api/v1/repositories/${repositoryId}/analysis-runs/${runId}`)
}

export function getRepository(repositoryId: string): Promise<RepositoryDetail> {
  return request(`/api/v1/repositories/${repositoryId}`)
}

export function getRepositoryBranches(repositoryId: string): Promise<BranchOut[]> {
  return request(`/api/v1/repositories/${repositoryId}/branches`)
}

export function getRepositoryProfile(repositoryId: string): Promise<RepositoryProfileResponse> {
  return request(`/api/v1/repositories/${repositoryId}/profile`)
}

export function listRepositories(page = 1, pageSize = 20): Promise<PaginatedRepositories> {
  return request(`/api/v1/repositories?page=${page}&page_size=${pageSize}`)
}
