// Mirrors backend/app/api/v1/schemas.py exactly.

export type IngestionStatus =
  | 'PENDING'
  | 'VALIDATING'
  | 'FETCHING_METADATA'
  | 'FETCHING_BRANCHES'
  | 'CLONING'
  | 'SCANNING'
  | 'READY'
  | 'FAILED'

// The real pipeline order -- used to render progress. Every entry here is
// a real IngestionStatus value; there is no synthetic/simulated step.
export const PIPELINE_STEPS: IngestionStatus[] = [
  'PENDING',
  'VALIDATING',
  'FETCHING_METADATA',
  'FETCHING_BRANCHES',
  'CLONING',
  'SCANNING',
  'READY',
]

export interface Repository {
  id: string
  provider: string
  source_url: string
  owner: string
  name: string
  default_branch: string | null
  description: string | null
  visibility: string
  primary_language: string | null
  license_name: string | null
  stargazers_count: number
  forks_count: number
  open_issues_count: number
  created_at: string
  updated_at: string
}

export interface Branch {
  id: number
  name: string
  head_commit_sha: string
  is_default: boolean
}

export interface AnalysisRun {
  id: number
  repository_id: string
  branch_id: number | null
  requested_branch: string | null
  commit_sha: string | null
  status: IngestionStatus
  last_error: { code: string; message: string } | null
  created_at: string
  updated_at: string
}

export interface IngestRepositoryResponse {
  repository: Repository
  analysis_run: AnalysisRun
}

export interface PaginatedRepositories {
  items: Repository[]
  total: number
  limit: number
  offset: number
}

export interface ApiErrorBody {
  error: {
    code: string
    message: string
  }
}
