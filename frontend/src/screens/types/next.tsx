/**
 * What to submit next: this tab's submittable Alphas ranked by how much each would lift the
 * combined book of everything already submitted, after trading costs. The quarterly payment
 * and level are judged on that book, so an Alpha that trades unlike the pool can be worth more
 * than a stronger one that repeats it.
 */

import { useQuery } from '@tanstack/react-query'
import { TrendingUpIcon } from 'lucide-react'
import { useState } from 'react'
import { fmt } from '@/lib/format'
import type { AlphaFilters } from '@/ui/alpha-filters'
import { Button, ErrorNotice, Notice, Panel, Segmented, Skeleton } from '@/ui/kit'
import { type Column, DataTable } from '@/ui/table'
import { type Kind, type NextRow, nextToSubmit } from './api'

const delta = (v: number | null | undefined) =>
  v == null ? '—' : `${v >= 0 ? '+' : ''}${fmt.ratio(v, 3)}`

const COLUMNS: Column<NextRow>[] = [
  {
    key: 'expression',
    header: 'Expression',
    width: 'minmax(220px,2.4fr)',
    cell: (r) => (
      <span className="truncate font-mono text-body-compact" title={r.expression ?? r.alphaId}>
        {r.expression ?? r.alphaId}
      </span>
    ),
  },
  { key: 'region', header: 'Region', width: '64px', cell: (r) => r.region ?? '—' },
  {
    key: 'sharpe',
    header: 'Own Sharpe',
    width: '92px',
    align: 'right',
    cell: (r) => <span className="num">{fmt.ratio(r.sharpe)}</span>,
  },
  {
    key: 'after',
    header: 'Combined IR after cost',
    width: '150px',
    align: 'right',
    cell: (r) => (
      <span
        className={`num ${(r.deltaIrAfterCost ?? 0) > 0 ? 'text-pnl-positive-text' : 'text-ink-subtle'}`}
      >
        {delta(r.deltaIrAfterCost)}
      </span>
    ),
  },
  {
    key: 'before',
    header: 'Before cost',
    width: '100px',
    align: 'right',
    cell: (r) => <span className="num text-ink-muted">{delta(r.deltaIr)}</span>,
  },
  {
    key: 'pool',
    header: 'Corr with book',
    width: '112px',
    align: 'right',
    cell: (r) => <span className="num">{fmt.ratio(r.poolCorrelation, 2)}</span>,
  },
  {
    key: 'max',
    header: 'Highest with one',
    width: '128px',
    align: 'right',
    cell: (r) => (
      <span
        className={`num ${(r.maxCorrelation ?? 0) >= 0.7 ? 'text-pnl-negative-text' : ''}`}
        title={r.maxCorrelationWith ?? undefined}
      >
        {fmt.ratio(r.maxCorrelation, 2)}
      </span>
    ),
  },
]

export function NextToSubmit({ kind, filters }: { kind: Kind; filters: AlphaFilters }) {
  const [asked, setAsked] = useState(false)
  const [cost, setCost] = useState(5)
  const plan = useQuery(nextToSubmit(kind, cost, filters, asked))
  const data = plan.data
  return (
    <Panel
      title="What to submit next"
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <Segmented
            label="Trading cost"
            items={[0, 2, 5, 10].map((b) => ({ value: b, label: `${b} bps` }))}
            value={cost}
            onChange={setCost}
          />
          {!asked && (
            <Button variant="primary" onClick={() => setAsked(true)}>
              <TrendingUpIcon aria-hidden />
              Rank for my combined book
            </Button>
          )}
        </div>
      }
    >
      <div className="flex flex-col gap-3">
        <p className="text-body-compact text-ink-subtle">
          Ranks this tab’s submittable and re-check Alphas (with the filters above) by how much each
          would change the combined IR of everything you have submitted, after trading costs. That
          combination is what quarterly performance is judged on. BRAIN does not publish its payment
          formula, so this is a guide, not a money figure. “Highest with one” is the strongest
          daily-PnL correlation with a single submitted Alpha; 0.7 or more usually fails
          self-correlation.
        </p>
        {plan.isError && <ErrorNotice error={plan.error} title="Could not rank" />}
        {asked && plan.isPending && <Skeleton label="Combining daily PnL" />}
        {data && (
          <>
            <p className="text-body-compact text-ink-muted">
              Your combined book today: <span className="num">{fmt.int(data.pool)}</span> submitted
              Alphas · IR <span className="num">{fmt.ratio(data.poolIr, 2)}</span> before cost ·{' '}
              <span className="num">{fmt.ratio(data.poolIrAfterCost, 2)}</span> after {data.costBps}{' '}
              bps.
            </p>
            {data.pool === 0 && (
              <Notice tone="warn" title="No submitted Alpha has its daily PnL stored">
                Download them on the Portfolio screen (Sync) so the book can be built.
              </Notice>
            )}
            {data.withoutSeries > 0 && (
              <p className="text-body-compact text-ink-subtle">
                {fmt.int(data.withoutSeries)} candidates were left out: their daily PnL is not
                downloaded yet (Alphas → sync).
              </p>
            )}
            <DataTable
              rows={data.rows}
              columns={COLUMNS}
              rowKey={(r) => r.alphaId}
              maxHeight="45vh"
              label="What to submit next"
            />
          </>
        )}
      </div>
    </Panel>
  )
}
