/**
 * Power Pool Correlation for a whole sweep at once, measured from the stored daily PnL.
 *
 * BRAIN answers this one Alpha at a time, slowly and under a rate limit, so checking a sweep
 * through it means opening a thousand Alphas by hand. The same figures come out of the series
 * already here — matched against BRAIN's own answers to four decimals on every row checked —
 * which turns that afternoon into a filter.
 */

import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { labTasks, type PowerPoolCorrelation, type PowerPoolRow } from '@/screens/tasks/api'

export type { PowerPoolRow }

export interface PowerPool {
  /** By Alpha id, for the rows a table already holds. */
  by: Map<string, PowerPoolRow>
  found: PowerPoolCorrelation | undefined
  pending: boolean
  error: unknown
  /** Measure again. The pool this is judged against changes whenever an Alpha is submitted
   *  and the Portfolio is synced, and nothing about that reaches this query on its own. */
  refresh: () => Promise<unknown>
  refreshing: boolean
}

/**
 * Its verdict, as a tone.
 *
 * `clear` is below BRAIN's ceiling and can be submitted on that count alone. `beats` is over
 * the ceiling but carries the Sharpe BRAIN wants over the Alpha it collides with — allowed,
 * and worth showing apart, because it rests on the pool staying as it is.
 */
export const powerPoolTone = (r: PowerPoolRow | undefined) =>
  r === undefined
    ? undefined
    : r.verdict === 'clear'
      ? 'clear'
      : r.verdict === 'beats'
        ? 'beats'
        : 'blocked'

export function usePowerPool(alphaIds: string[]): PowerPool {
  const query = useQuery({
    // The id list is part of the key: a different set of Alphas is a different answer, and a
    // stale one is worse than a second's wait.
    queryKey: ['power-pool', alphaIds],
    queryFn: () => labTasks.powerPoolFor(alphaIds),
    enabled: alphaIds.length > 0,
    retry: false,
    staleTime: 60_000,
  })
  const by = useMemo(
    () => new Map((query.data?.rows ?? []).map((r) => [r.alphaId, r])),
    [query.data],
  )
  return {
    by,
    found: query.data,
    pending: query.isPending,
    error: query.error,
    refresh: () => query.refetch(),
    // `isFetching` rather than `isPending`: a re-measure keeps the last answer on screen, so
    // the table does not empty itself for the two seconds it takes.
    refreshing: query.isFetching,
  }
}
