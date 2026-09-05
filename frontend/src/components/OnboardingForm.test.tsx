import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { OnboardingForm } from './OnboardingForm'

describe('OnboardingForm', () => {
  it('calls onSubmit with the URL and null branch when branch is left blank', () => {
    const onSubmit = vi.fn()
    render(<OnboardingForm onSubmit={onSubmit} submitting={false} errorMessage={null} />)

    fireEvent.change(screen.getByLabelText(/github repository url/i), {
      target: { value: 'https://github.com/octocat/hello-world' },
    })
    fireEvent.click(screen.getByRole('button', { name: /analyze repository/i }))

    expect(onSubmit).toHaveBeenCalledWith('https://github.com/octocat/hello-world', null)
  })

  it('trims and passes a branch when one is entered', () => {
    const onSubmit = vi.fn()
    render(<OnboardingForm onSubmit={onSubmit} submitting={false} errorMessage={null} />)

    fireEvent.change(screen.getByLabelText(/github repository url/i), {
      target: { value: 'https://github.com/octocat/hello-world' },
    })
    fireEvent.change(screen.getByLabelText(/branch/i), { target: { value: '  dev  ' } })
    fireEvent.click(screen.getByRole('button', { name: /analyze repository/i }))

    expect(onSubmit).toHaveBeenCalledWith('https://github.com/octocat/hello-world', 'dev')
  })

  it('does not submit an empty URL', () => {
    const onSubmit = vi.fn()
    const { container } = render(<OnboardingForm onSubmit={onSubmit} submitting={false} errorMessage={null} />)

    fireEvent.submit(container.querySelector('form')!)

    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('disables the submit button and shows submitting text while in flight', () => {
    render(<OnboardingForm onSubmit={vi.fn()} submitting={true} errorMessage={null} />)
    const button = screen.getByRole('button', { name: /starting ingestion/i })
    expect(button).toBeDisabled()
  })

  it('renders an error message when provided', () => {
    render(<OnboardingForm onSubmit={vi.fn()} submitting={false} errorMessage="Something went wrong" />)
    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
  })
})
