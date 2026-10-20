/** Correlation of the selected Alphas' daily PnL, as a heatmap that fills the panel. */

import { cn } from '@/lib/cn'
import { fmt } from '@/lib/format'
import type { PortfolioResult } from './api'

/** Deepest mix at ±1. Kept short of full so the white figure on it stays readable. */
const DEEPEST = 70

/** Positive correlation deepens toward red: the pair moves together and adds little (BRAIN
 * refuses a Power Pool pair at 0.5). Negative deepens toward green: the pair diversifies. */
function fill(value: number) {
  const hue = value >= 0 ? 'var(--color-pnl-negative)' : 'var(--color-pnl-positive)'
  const share = Math.round(Math.min(1, Math.abs(value)) * DEEPEST)
  return `color-mix(in oklab, ${hue} ${share}%, var(--color-surface-1))`
}

const LEGEND = `linear-gradient(to right, ${[-1, -0.5, 0, 0.5, 1].map(fill).join(', ')})`

/** Past its grid limit the backend sends only the most correlated pairs, highest first. */
function TopPairs({ result }: { result: PortfolioResult }) {
  const { ids, topPairs, measuredPairs } = result
  if (!topPairs.length) {
    return (
      <p className="text-body-compact text-ink-subtle">
        No two of these {ids.length} Alphas share the 250 trading days a correlation needs.
      </p>
    )
  }
  return (
    <div className="flex flex-col gap-3">
      <p className="text-body-compact text-ink-subtle">
        The {topPairs.length} most correlated of{' '}
        <span className="num">{fmt.int(measuredPairs)}</span> pairs; a full grid of {ids.length}{' '}
        Alphas is too dense to read.
      </p>
      <div className="grid gap-1.5 sm:grid-cols-2 xl:grid-cols-4">
        {topPairs.map((p) => (
          <div
            key={`${p.a}-${p.b}`}
            className="flex items-center justify-between gap-3 rounded-xs px-3 py-2 text-body-compact"
            style={{ background: fill(p.correlation) }}
          >
            <span className="mono-metric text-ink-muted">
              {p.a} · {p.b}
            </span>
            <span className="num text-ink">{fmt.ratio(p.correlation)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export function CorrelationMatrix({ result }: { result: PortfolioResult }) {
  const { ids, correlation } = result
  // The backend decides: a grid it can send, or only the top pairs when it cannot.
  if (!correlation.length) return <TopPairs result={result} />
  return (
    <div className="flex flex-col gap-3">
      <div className="overflow-x-auto">
        <table
          className="w-full table-fixed border-separate border-spacing-px"
          style={{ minWidth: `${6 + ids.length * 4.5}rem` }}
        >
          <thead>
            <tr>
              <th className="w-24" />
              {ids.map((id) => (
                <th
                  key={id}
                  className="mono-metric truncate pb-1.5 text-center font-normal text-ink-subtle"
                >
                  {id}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ids.map((row, i) => (
              <tr key={row}>
                <th className="mono-metric truncate pr-3 text-left font-normal text-ink-subtle">
                  {row}
                </th>
                {ids.map((column, j) => {
                  const value = correlation[i]?.[j] ?? null
                  const self = i === j
                  return (
                    <td
                      key={column}
                      title={`${row} · ${column}`}
                      className={cn(
                        'num h-11 text-center text-body-compact',
                        self ? 'bg-surface-3 text-ink-subtle' : 'text-ink',
                      )}
                      style={{ background: self || value === null ? undefined : fill(value) }}
                    >
                      {value === null ? '' : fmt.ratio(value)}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center gap-2 text-body-compact text-ink-subtle">
        <span className="num">−1</span>
        <span className="h-2 w-48 rounded-pill" style={{ background: LEGEND }} aria-hidden />
        <span className="num">+1</span>
      </div>
    </div>
  )
}
