import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import StatusBadge from './StatusBadge'

describe('StatusBadge', () => {
  it('renders Unknown for null status', () => {
    render(<StatusBadge status={null} />)
    expect(screen.getByText('Unknown')).toBeInTheDocument()
    expect(screen.getByText('Unknown')).toHaveClass('badge-unknown')
  })

  it('renders success variant for READY', () => {
    render(<StatusBadge status="READY" />)
    expect(screen.getByText('Ready')).toHaveClass('badge-success')
  })

  it('renders danger variant for FAILED', () => {
    render(<StatusBadge status="FAILED" />)
    expect(screen.getByText('Failed')).toHaveClass('badge-danger')
  })

  it.each(['QUEUED', 'VALIDATING', 'FETCHING', 'CLONING', 'ANALYZING'] as const)(
    'renders progress variant for %s',
    (status) => {
      render(<StatusBadge status={status} />)
      const label = status[0] + status.slice(1).toLowerCase()
      expect(screen.getByText(label)).toHaveClass('badge-progress')
    },
  )
})
