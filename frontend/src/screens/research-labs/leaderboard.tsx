/**
 * Template leaderboard: each template, built-in shape and SuperAlpha recipe by how often its
 * alphas pass for you, best first, once it has five results. Run the strong ones more; drop
 * the weak ones.
 */

import { useQuery } from '@tanstack/react-query'
import { TrophyIcon } from 'lucide-react'
import type { components } from '@/api/generated'
import { http } from '@/api/http'
import { fmt } from '@/lib/format'
import { Empty, ErrorNotice, Panel, Skeleton } from '@/ui/kit'
import { type Column, DataTable } from '@/ui/table'

type Score = components['schemas']['TemplateScore']

const COLUMNS: Column<Score>[] = [
  {
    key: 'lab',
    header: 'Lab',
    width: '170px',
    cell: (r) => <span className="truncate">{r.lab}</span>,
  },
  {
    key: 'name',
    header: 'Template, shape or recipe',
    width: 'minmax(240px,3fr)',
    cell: (r) => (
      <span className="truncate font-mono text-body-compact" title={r.name}>
        {r.name}
      </span>
    ),
  },
  {
    key: 'rate',
    header: 'Pass rate',
    width: '96px',
    align: 'right',
    cell: (r) => (
      <span
        className={`num ${r.passRate >= 0.1 ? 'text-pnl-positive-text' : r.passRate === 0 ? 'text-ink-subtle' : ''}`}
      >
        {fmt.pct(r.passRate, 1)}
      </span>
    ),
  },
  {
    key: 'passed',
    header: 'Passed',
    width: '80px',
    align: 'right',
    cell: (r) => <span className="num">{fmt.int(r.passed)}</span>,
  },
  {
    key: 'simulated',
    header: 'Results',
    width: '80px',
    align: 'right',
    cell: (r) => <span className="num">{fmt.int(r.simulated)}</span>,
  },
  {
    key: 'sharpe',
    header: 'Mean Sharpe',
    width: '104px',
    align: 'right',
    cell: (r) => <span className="num">{fmt.ratio(r.meanSharpe)}</span>,
  },
]

export function TemplateLeaderboard() {
  const scores = useQuery({
    queryKey: ['overview', 'templates'],
    queryFn: () => http.get<Score[]>('/api/overview/templates'),
    staleTime: 5 * 60_000,
  })
  return (
    <Panel
      title="Which templates pay"
      description="Each template, Search Lab shape, Region Agnostic shape and SuperAlpha recipe, by the share of its alphas that are submittable, need a re-check or were submitted. Shown once it has 5 results. Run the top ones more; drop the ones at 0%."
    >
      {scores.isPending && <Skeleton className="h-40 w-full" label="Reading results" />}
      {scores.isError && <ErrorNotice error={scores.error} title="Could not read the results" />}
      {scores.data && scores.data.length === 0 && (
        <Empty icon={<TrophyIcon />} title="Not enough results yet">
          A template appears here once five of its alphas are back.
        </Empty>
      )}
      {scores.data && scores.data.length > 0 && (
        <DataTable
          rows={scores.data}
          columns={COLUMNS}
          rowKey={(r) => `${r.lab}|${r.name}`}
          label="Template leaderboard"
          maxHeight="50vh"
        />
      )}
    </Panel>
  )
}
