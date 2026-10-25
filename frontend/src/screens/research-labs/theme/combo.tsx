/**
 * What to submit next for a theme judged on its combination. The theme ranks a user's theme
 * Alphas as one equal-weight book: Combo IR before cost (BC) and after cost (AC), and an
 * out-of-sample score before and after cost. A strong Alpha that repeats one already submitted
 * adds little to that book, so candidates are ranked on what they add to it, and the picks are
 * chosen one after another, each against the pool and the picks before it.
 */

import { useQuery } from '@tanstack/react-query'
import { TrendingUpIcon } from 'lucide-react'
import { useState } from 'react'
import type { components } from '@/api/generated'
import { http, qs } from '@/api/http'
import { fmt } from '@/lib/format'
import { PresubmitButton } from '@/screens/types/presubmit'
import { Button, ErrorNotice, Notice, Panel, Segmented, Skeleton } from '@/ui/kit'
import { type Column, DataTable } from '@/ui/table'

type ThemeCombo = components['schemas']['ThemeCombo']
type ComboRow = components['schemas']['ComboRow']

const delta = (v: number | null | undefined) =>
  v == null ? '—' : `${v >= 0 ? '+' : ''}${fmt.ratio(v, 3)}`

const money = (v: number | null | undefined) => (v == null ? '—' : `$${fmt.compact(v)}`)

const tone = (v: number | null | undefined) =>
  v == null ? 'text-ink-subtle' : v > 0 ? 'text-pnl-positive-text' : 'text-pnl-negative-text'

const COLUMNS: Column<ComboRow>[] = [
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
  {
    key: 'sharpe',
    header: 'Sharpe',
    width: '72px',
    align: 'right',
    cell: (r) => <span className="num">{fmt.ratio(r.sharpe)}</span>,
  },
  {
    key: 'regions',
    header: 'AMER / APAC / EMEA',
    width: '150px',
    align: 'right',
    cell: (r) => (
      <span className="num">
        {[r.amerSharpe, r.apacSharpe, r.emeaSharpe].map((v, i) => (
          <span key={i} className={v != null && v <= 1 ? 'text-pnl-negative-text' : ''}>
            {i > 0 ? ' / ' : ''}
            {fmt.ratio(v)}
          </span>
        ))}
      </span>
    ),
  },
  {
    key: 'turnover',
    header: 'Turnover',
    width: '80px',
    align: 'right',
    cell: (r) => <span className="num">{fmt.pct(r.turnover)}</span>,
  },
  ...(
    [
      ['bc', 'BC Combo IR', 'bcIr'],
      ['ac', 'AC Combo IR', 'acIr'],
      ['os', 'OS (2y)', 'osIr'],
      ['acos', 'AC OS (2y)', 'acOsIr'],
    ] as const
  ).map(
    ([key, header, field]): Column<ComboRow> => ({
      key,
      header,
      width: '104px',
      align: 'right',
      // The change it makes; the combination it leads to on hover.
      cell: (r) => (
        <span
          className={`num ${tone(r.delta[field])}`}
          title={`Combination with it: ${fmt.ratio(r.combo[field], 2)}`}
        >
          {delta(r.delta[field])}
        </span>
      ),
    }),
  ),
  {
    key: 'pnl',
    header: 'Merged PnL',
    width: '104px',
    align: 'right',
    cell: (r) => (
      <span
        className={`num ${tone(r.delta.pnl)}`}
        title={`Merged PnL with it: ${money(r.combo.pnl)}`}
      >
        {r.delta.pnl == null
          ? '—'
          : `${r.delta.pnl >= 0 ? '+' : '−'}${money(Math.abs(r.delta.pnl))}`}
      </span>
    ),
  },
  {
    key: 'max',
    header: 'Highest with one',
    width: '120px',
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
  {
    key: 'check',
    header: 'Before you submit',
    width: 'minmax(190px,1.3fr)',
    cell: (r) => <PresubmitButton alphaId={r.alphaId} />,
  },
]

export function ThemeComboPanel({ theme }: { theme: string }) {
  const [asked, setAsked] = useState(false)
  const [cost, setCost] = useState(5)
  const plan = useQuery({
    queryKey: ['theme-lab', 'combo', theme, cost],
    queryFn: () =>
      http.get<ThemeCombo>(`/api/theme-lab/combo${qs({ theme, costBps: cost, picks: 15 })}`),
    enabled: asked,
  })
  const data = plan.data
  return (
    <Panel
      title="What to submit next for this theme"
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <Segmented
            label="Trading cost"
            items={[2, 5, 10].map((b) => ({ value: b, label: `${b} bps` }))}
            value={cost}
            onChange={setCost}
          />
          <Button
            variant={asked ? 'secondary' : 'primary'}
            loading={plan.isFetching}
            onClick={() => (asked ? void plan.refetch() : setAsked(true))}
          >
            <TrendingUpIcon aria-hidden />
            {asked ? 'Rank again' : 'Rank for the theme combo'}
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-3">
        <p className="text-body-compact text-pretty text-ink-subtle">
          Your submittable Power Pool Alphas that fit this theme, ranked by how much each lifts the
          figures BRAIN’s Power Pool leaderboard shows for your merged theme Alphas: BC Combo IR and
          AC Combo IR count most, with the same over the last two years as a check that a pick does
          not live on an old stretch (BRAIN’s OS score is measured after you submit). Merged PnL is
          estimated from the stored daily PnL. The picks are chosen in order, each against what you
          submitted in the theme’s dates and the picks above it, so two Alphas that trade alike are
          not both picked. Spends no quota.
        </p>
        {plan.isError && <ErrorNotice error={plan.error} title="Could not rank" />}
        {asked && plan.isPending && <Skeleton label="Combining daily PnL" />}
        {data && (
          <>
            <p className="text-body-compact text-ink-muted">
              As the leaderboard reads you now: tagged Power Pool Alphas{' '}
              <span className="num">{fmt.int(data.pool)}</span> · Merged PnL{' '}
              <span className="num">{money(data.now.pnl)}</span> · BC Combo IR{' '}
              <span className="num">{fmt.ratio(data.now.bcIr, 2)}</span> · AC Combo IR{' '}
              <span className="num">{fmt.ratio(data.now.acIr, 2)}</span> · last 2 years{' '}
              <span className="num">{fmt.ratio(data.now.osIr, 2)}</span> /{' '}
              <span className="num">{fmt.ratio(data.now.acOsIr, 2)}</span> ·{' '}
              {fmt.int(data.candidates)} candidates
            </p>
            {data.downloading > 0 && (
              <Notice tone="info" title={`Downloading daily PnL for ${fmt.int(data.downloading)}`}>
                They are left out until it arrives (no quota is spent). Rank again in a few minutes.
              </Notice>
            )}
            {data.candidates === 0 && (
              <Notice tone="warn" title="No submittable Alpha fits this theme yet">
                Run the lab above; passing Alphas appear here once BRAIN’s checks are back.
              </Notice>
            )}
            {data.picks.length > 0 && (
              <>
                <h3 className="text-title font-medium text-ink">Submit in this order</h3>
                <DataTable
                  rows={data.picks}
                  columns={COLUMNS}
                  rowKey={(r) => r.alphaId}
                  maxHeight="40vh"
                  label="Submit in this order"
                />
              </>
            )}
            {data.rows.length > 0 && (
              <>
                <h3 className="text-title font-medium text-ink">
                  Every candidate against what you have submitted
                </h3>
                <DataTable
                  rows={data.rows}
                  columns={COLUMNS}
                  rowKey={(r) => r.alphaId}
                  maxHeight="40vh"
                  label="Every candidate"
                />
              </>
            )}
          </>
        )}
      </div>
    </Panel>
  )
}
