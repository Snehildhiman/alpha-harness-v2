/** A clock that re-renders its component, for the figures that are only true this second. */

import { useEffect, useState } from 'react'

/**
 * The current time, refreshed every `every` milliseconds.
 *
 * A duration drawn from `Date.now()` at render is frozen until something else happens to
 * re-render: a task's elapsed time then sits still between WebSocket broadcasts and reads
 * as a stalled task rather than a stalled clock. Pass `0` to stop ticking — a finished
 * task's elapsed time is fixed, and a timer behind it would be a wakeup a second forever.
 */
export function useNow(every: number): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (every <= 0) return
    setNow(Date.now())
    const timer = setInterval(() => setNow(Date.now()), every)
    return () => clearInterval(timer)
  }, [every])
  return now
}
