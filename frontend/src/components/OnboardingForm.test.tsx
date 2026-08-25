import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api'
import type { IngestRepositoryResponse } from '../api'
import OnboardingForm from './OnboardingForm'

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api')
  return { ...actual, ingestRepository: vi.fn() }
})

import { ingestRepository } from '../api'

describe('OnboardingForm', () => {
  beforeEach(() => {
    vi.mocked(ingestRepository).mockReset()
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('shows a validation error and does not call the API on empty submission', async () => {
    const user = userEvent.setup()
    const onStarted = vi.fn()
    render(<OnboardingForm onStarted={onStarted} />)

    await user.click(screen.getByRole('button', { name: /analyze repository/i }))

    expect(screen.getByRole('alert')).toHaveTextContent(/enter a github repository url/i)
    expect(ingestRepository).not.toHaveBeenCalled()
    expect(onStarted).not.toHaveBeenCalled()
  })

  it('treats a whitespace-only URL as empty', async () => {
    const user = userEvent.setup()
    render(<OnboardingForm onStarted={vi.fn()} />)

    await user.type(screen.getByLabelText(/repository url/i), '   ')
    await user.click(screen.getByRole('button', { name: /analyze repository/i }))

    expect(screen.getByRole('alert')).toHaveTextContent(/enter a github repository url/i)
    expect(ingestRepository).not.toHaveBeenCalled()
  })

  it('submits the trimmed URL/branch, calls onStarted, and clears the form', async () => {
    vi.mocked(ingestRepository).mockResolvedValue({
      repository_id: 'repo-1',
      analysis_run_id: 'run-1',
      provider: 'github',
      source_url: 'https://github.com/octocat/Hello-World',
      name: 'Hello-World',
      owner: 'octocat',
      selected_branch: null,
      commit_sha: null,
      status: 'QUEUED',
      error_code: null,
      error_message: null,
    })
    const user = userEvent.setup()
    const onStarted = vi.fn()
    render(<OnboardingForm onStarted={onStarted} />)

    await user.type(screen.getByLabelText(/repository url/i), '  https://github.com/octocat/Hello-World  ')
    await user.type(screen.getByLabelText(/branch/i), '  main  ')
    await user.click(screen.getByRole('button', { name: /analyze repository/i }))

    await waitFor(() => expect(onStarted).toHaveBeenCalledWith('repo-1', 'run-1'))
    expect(ingestRepository).toHaveBeenCalledWith('https://github.com/octocat/Hello-World', 'main')
    expect(screen.getByLabelText(/repository url/i)).toHaveValue('')
    expect(screen.getByLabelText(/branch/i)).toHaveValue('')
  })

  it('displays the ApiError message and keeps the entered values on failure', async () => {
    vi.mocked(ingestRepository).mockRejectedValue(new ApiError('INVALID_URL', 'That is not a GitHub URL', 422))
    const user = userEvent.setup()
    render(<OnboardingForm onStarted={vi.fn()} />)

    await user.type(screen.getByLabelText(/repository url/i), 'not-a-url')
    await user.click(screen.getByRole('button', { name: /analyze repository/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent('That is not a GitHub URL')
    expect(screen.getByLabelText(/repository url/i)).toHaveValue('not-a-url')
  })

  it('shows a generic message for a non-ApiError failure', async () => {
    vi.mocked(ingestRepository).mockRejectedValue(new Error('boom'))
    const user = userEvent.setup()
    render(<OnboardingForm onStarted={vi.fn()} />)

    await user.type(screen.getByLabelText(/repository url/i), 'https://github.com/octocat/Hello-World')
    await user.click(screen.getByRole('button', { name: /analyze repository/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not start analysis/i)
  })

  it('disables the submit button and inputs while submitting, and re-enables after failure', async () => {
    let resolveIngest: (v: IngestRepositoryResponse) => void = () => {}
    vi.mocked(ingestRepository).mockReturnValue(
      new Promise((resolve) => {
        resolveIngest = resolve
      }),
    )
    const user = userEvent.setup()
    render(<OnboardingForm onStarted={vi.fn()} />)

    await user.type(screen.getByLabelText(/repository url/i), 'https://github.com/octocat/Hello-World')
    const button = screen.getByRole('button', { name: /analyze repository/i })
    await user.click(button)

    expect(button).toBeDisabled()
    expect(screen.getByLabelText(/repository url/i)).toBeDisabled()
    expect(button).toHaveTextContent(/starting/i)

    resolveIngest({
      repository_id: 'r',
      analysis_run_id: 'a',
      provider: 'github',
      source_url: '',
      name: '',
      owner: '',
      selected_branch: null,
      commit_sha: null,
      status: 'QUEUED',
      error_code: null,
      error_message: null,
    })
    await waitFor(() => expect(button).not.toBeDisabled())
  })

  it('does not fire duplicate requests on rapid repeated clicks (button disables on first click)', async () => {
    let resolveIngest: (v: IngestRepositoryResponse) => void = () => {}
    vi.mocked(ingestRepository).mockReturnValue(
      new Promise((resolve) => {
        resolveIngest = resolve
      }),
    )
    const user = userEvent.setup()
    render(<OnboardingForm onStarted={vi.fn()} />)

    await user.type(screen.getByLabelText(/repository url/i), 'https://github.com/octocat/Hello-World')
    const button = screen.getByRole('button', { name: /analyze repository/i })
    await user.click(button)
    // Second click while disabled must not fire a second request.
    await user.click(button)

    expect(ingestRepository).toHaveBeenCalledTimes(1)
    resolveIngest({
      repository_id: 'r',
      analysis_run_id: 'a',
      provider: 'github',
      source_url: '',
      name: '',
      owner: '',
      selected_branch: null,
      commit_sha: null,
      status: 'QUEUED',
      error_code: null,
      error_message: null,
    })
  })
})
