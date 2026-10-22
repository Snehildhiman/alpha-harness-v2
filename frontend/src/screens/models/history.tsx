/**
 * Model accuracy over time: each target's test score at every training, so it is plain
 * whether the models get better as results arrive. AUC for a check (0.5 is a coin), rank
 * correlation for a number (0 is no skill); higher is better for both.
 */

import { useQuery } from '@tanstack/react-query'
import type { components } from '@/api/generated'
import { http } from '@/api/http'
import { fmt } from '@/lib/format'
import { Empty, ErrorNotice, Panel, Skeleton } from '@/ui/kit'

type Point = components['schemas']['HistoryPoint']

interface Series {
  target: string
  label: string
  kind: string
  values: { at: string; score: number; accepted: boolean }[]
}

function series(points: Point[]): Series[] {
  const by = new Map<string, Series>()
  for (const p of points) {
    for (const t of p.targets) {
      if (t.score == null) continue
      const s = by.get(t.target) ?? { target: t.target, label: t.label, kind: t.kind, values: [] }
      s.values.push({ at: p.trainedAt, score: t.score, accepted: p.accepted })
      by.set(t.target, s)
    }
  }
  return [...by.values()].sort((a, b) => a.label.localeCompare(b.label))
}

function Spark({ values }: { values: Series['values'] }) {
  const w = 160
  const h = 36
  const scores = values.map((v) => v.score)
  const lo = Math.min(...scores)
  const hi = Math.max(...scores)
  const span = hi - lo || 1
  const x = (i: number) => (values.length === 1 ? w / 2 : (i / (values.length - 1)) * (w - 8) + 4)
  const y = (v: number) => h - 4 - ((v - lo) / span) * (h - 8)
  const path = values.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v.score).toFixed(1)}`)
  return (
    <svg width={w} height={h} role="img" aria-label="Score at each training" className="shrink-0">
      <path
        d={path.join(' ')}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        className="text-ink-muted"
      />
      {values.map((v, i) => (
        <circle
          key={v.at}
          cx={x(i)}
          cy={y(v.score)}
          r={2.5}
          className={v.accepted ? 'fill-ink' : 'fill-surface-3 stroke-ink-subtle'}
        >
          <title>{`${fmt.dateTime(v.at)}: ${v.score.toFixed(3)}${v.accepted ? '' : ' (not kept)'}`}</title>
        </circle>
      ))}
    </svg>
  )
}

export function ModelHistory() {
  const history = useQuery({
    queryKey: ['models', 'history'],
    queryFn: () => http.get<Point[]>('/api/models/history'),
  })
  const all = history.data ? series(history.data) : []
  return (
    <Panel
      title="Accuracy over time"
      description="Each target's score on alphas it never saw, at every training. AUC for a check (0.5 is a coin toss), rank correlation for a number (0 is no skill). Hollow points are retrains that did worse and were not kept."
    >
      {history.isPending && <Skeleton className="h-40 w-full" label="Reading the history" />}
      {history.isError && <ErrorNotice error={history.error} title="Could not read the history" />}
      {history.data && all.length === 0 && (
        <Empty title="No training yet">
          Train the models once and their first point appears here.
        </Empty>
      )}
      {all.length > 0 && (
        <ul className="grid grid-cols-1 gap-x-8 gap-y-2 lg:grid-cols-2">
          {all.map((s) => {
            const first = s.values[0]?.score ?? 0
            const last = s.values.at(-1)?.score ?? 0
            const change = last - first
            return (
              <li key={s.target} className="flex items-center gap-3">
                <span className="w-56 truncate text-body-compact text-ink" title={s.target}>
                  {s.label}
                </span>
                <Spark values={s.values} />
                <span className="num w-14 text-right text-body-compact">{last.toFixed(3)}</span>
                <span
                  className={`num w-16 text-right text-body-compact ${change > 0.005 ? 'text-pnl-positive-text' : change < -0.005 ? 'text-pnl-negative-text' : 'text-ink-subtle'}`}
                >
                  {s.values.length > 1 ? `${change >= 0 ? '+' : ''}${change.toFixed(3)}` : '—'}
                </span>
              </li>
            )
          })}
        </ul>
      )}
    </Panel>
  )
}
