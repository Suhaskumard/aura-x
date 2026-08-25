import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { usePolling } from './usePolling'

async function flush() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0)
  })
}

describe('usePolling', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('fetches immediately on mount and stores the result', async () => {
    const fetcher = vi.fn().mockResolvedValue({ status: 'PENDING' })
    const { result } = renderHook(() => usePolling(fetcher, 1000, (v: { status: string }) => v.status === 'DONE', []))

    await flush()
    expect(result.current.value).toEqual({ status: 'PENDING' })
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it('reschedules on the interval while not terminal, and stops once terminal', async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce({ status: 'PENDING' })
      .mockResolvedValueOnce({ status: 'PENDING' })
      .mockResolvedValueOnce({ status: 'DONE' })
    const { result } = renderHook(() => usePolling(fetcher, 1000, (v: { status: string }) => v.status === 'DONE', []))

    await flush()
    expect(fetcher).toHaveBeenCalledTimes(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000)
    })
    expect(fetcher).toHaveBeenCalledTimes(2)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000)
    })
    expect(fetcher).toHaveBeenCalledTimes(3)
    expect(result.current.value).toEqual({ status: 'DONE' })

    // No further polling once terminal.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000)
    })
    expect(fetcher).toHaveBeenCalledTimes(3)
  })

  it('surfaces a fetch error but keeps retrying on the interval', async () => {
    const fetcher = vi
      .fn()
      .mockRejectedValueOnce(new Error('network down'))
      .mockResolvedValueOnce({ status: 'DONE' })
    const { result } = renderHook(() => usePolling(fetcher, 1000, (v: { status: string }) => v.status === 'DONE', []))

    await flush()
    expect(result.current.error).toBe('network down')
    expect(result.current.value).toBeNull()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000)
    })
    expect(result.current.error).toBeNull()
    expect(result.current.value).toEqual({ status: 'DONE' })
  })

  it('does not update state after the component unmounts (no stale write)', async () => {
    let resolveFetch: (value: { status: string }) => void = () => {}
    const fetcher = vi.fn().mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveFetch = resolve
        }),
    )
    const { result, unmount } = renderHook(() =>
      usePolling(fetcher, 1000, (v: { status: string }) => v.status === 'DONE', []),
    )

    unmount()
    await act(async () => {
      resolveFetch({ status: 'DONE' })
      await Promise.resolve()
    })
    // value stays at its initial null because the hook unmounted before the fetch resolved.
    expect(result.current.value).toBeNull()
  })

  it('resets value/error and restarts polling from scratch when deps change', async () => {
    const fetcher = vi.fn().mockResolvedValue({ status: 'DONE' })
    const { result, rerender } = renderHook(
      ({ id }: { id: string }) => usePolling(fetcher, 1000, (v: { status: string }) => v.status === 'DONE', [id]),
      { initialProps: { id: 'a' } },
    )

    await flush()
    expect(result.current.value).toEqual({ status: 'DONE' })
    expect(fetcher).toHaveBeenCalledTimes(1)

    rerender({ id: 'b' })
    // Immediately after deps change (before the new fetch resolves), state is cleared.
    expect(result.current.value).toBeNull()
    expect(result.current.error).toBeNull()

    await flush()
    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it('clears the pending timer on unmount so no orphaned poll fires later', async () => {
    const fetcher = vi.fn().mockResolvedValue({ status: 'PENDING' })
    const { unmount } = renderHook(() => usePolling(fetcher, 1000, (v: { status: string }) => v.status === 'DONE', []))

    await flush()
    expect(fetcher).toHaveBeenCalledTimes(1)
    unmount()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000)
    })
    expect(fetcher).toHaveBeenCalledTimes(1)
  })
})
