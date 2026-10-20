/**
 * Scorecards: which operators, operator pairs, fields, datasets, data categories, lookbacks and
 * settings come with high or low correlation (or pass rate, or Sharpe) across the vault. Each
 * part is ranked by its mean pulled toward the vault's, so a part seen twice cannot top a list.
 */

import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { fmt } from '@/lib/format'
import { ErrorNotice, Page, PageHeader, Panel, Segmented, TEXT_TONE, type Tone } from '@/ui/kit'
import { type Column, DataTable } from '@/ui/table'
import { type CardRow, type Metric, type Part, scorecards } from './api'

const PARTS: { value: Part; label: string }[] = [
  { value: 'operator', label: 'Operators' },
  { value: 'pair', label: 'Operator pairs' },
  { value: 'field', label: 'Fields' },
  { value: 'dataset', label: 'Datasets' },
  { value: 'category', label: 'Categories' },
  { value: 'lookback', label: 'Lookbacks' },
  { value: 'neutralization', label: 'Neutralization' },
  { value: 'region', label: 'Region' },
]

/** Whether a higher value is good news, which decides the colour of a lift. */
interface MetricInfo {
  value: Metric
  label: string
  higherIsBetter: boolean
  rate: boolean
}
const PROD: MetricInfo = {
  value: 'prod_corr',
  label: 'Prod corr',
  higherIsBetter: false,
  rate: false,
}
const METRICS: MetricInfo[] = [
  PROD,
  { value: 'power_pool_corr', label: 'Power Pool corr', higherIsBetter: false, rate: false },
  { value: 'self_corr', label: 'Self corr', higherIsBetter: false, rate: false },
  { value: 'check:PROD_CORRELATION', label: 'Prod pass rate', higherIsBetter: true, rate: true },
  {
    value: 'check:POWER_POOL_CORRELATION',
    label: 'Power Pool pass rate',
    higherIsBetter: true,
    rate: true,
  },
  { value: 'sharpe', label: 'Sharpe', higherIsBetter: true, rate: false },
]

const MIN_ALPHAS = [
  { value: 5, label: '5+' },
  { value: 20, label: '20+' },
  { value: 100, label: '100+' },
]

function columns(metric: MetricInfo): Column<CardRow>[] {
  const show = (v: number) => (metric.rate ? fmt.pct(v) : fmt.ratio(v))
  const tone = (lift: number): Tone =>
    Math.abs(lift) < 0.005 ? 'muted' : lift > 0 === metric.higherIsBetter ? 'profit' : 'loss'
  return [
    {
      key: 'name',
      header: 'Part',
      width: 'minmax(180px,2fr)',
      cell: (r) => (
        <span className="truncate font-mono text-body-compact" title={r.name}>
          {r.name}
        </span>
      ),
    },
    {
      key: 'measured',
      header: 'Alphas',
      width: '72px',
      align: 'right',
      cell: (r) => <span className="num text-ink-subtle">{fmt.int(r.measured)}</span>,
    },
    {
      key: 'mean',
      header: 'Mean',
      width: '76px',
      align: 'right',
      cell: (r) => <span className="num">{show(r.mean)}</span>,
    },
    {
      key: 'lift',
      header: 'Vs vault',
      width: '84px',
      align: 'right',
      cell: (r) => (
        <span className={`num ${TEXT_TONE[tone(r.lift)]}`} title={`Shrunk mean ${show(r.shrunk)}`}>
          {r.lift > 0 ? '+' : ''}
          {show(r.lift)}
        </span>
      ),
    },
  ]
}

export function ScorecardsScreen() {
  const [part, setPart] = useState<Part>('operator')
  const [metric, setMetric] = useState<Metric>('prod_corr')
  const [minAlphas, setMinAlphas] = useState(20)
  const page = useQuery({
    ...scorecards({ part, metric, minAlphas, limit: 25 }),
    placeholderData: keepPreviousData,
  })
  const meta = METRICS.find((m) => m.value === metric) ?? PROD
  const cols = columns(meta)
  const overall = page.data?.overall
  const worse = meta.higherIsBetter ? 'Lowest' : 'Highest'
  const better = meta.higherIsBetter ? 'Highest' : 'Lowest'
  // A part lands on one side only: worse than the vault on this metric, or better.
  const bad = (r: CardRow) => (meta.higherIsBetter ? r.lift < 0 : r.lift > 0)
  const avoid = ((meta.higherIsBetter ? page.data?.lowest : page.data?.highest) ?? []).filter(bad)
  const more = ((meta.higherIsBetter ? page.data?.highest : page.data?.lowest) ?? []).filter(
    (r) => !bad(r),
  )

  return (
    <Page>
      <PageHeader
        title="Scorecards"
        description="Which building blocks come with high or low correlation in your vault, so you know what to build more of and what to avoid. Every re-check and simulation updates them."
      />
      <Panel>
        <div className="flex flex-col gap-3">
          <Segmented label="Part" items={PARTS} value={part} onChange={setPart} />
          <div className="flex flex-wrap items-center gap-3">
            <Segmented
              label="Metric"
              items={METRICS.map(({ value, label }) => ({ value, label }))}
              value={metric}
              onChange={setMetric}
            />
            <Segmented
              label="Seen in at least"
              items={MIN_ALPHAS}
              value={minAlphas}
              onChange={setMinAlphas}
            />
          </div>
          <p className="text-body-compact text-ink-subtle">
            {overall === null || overall === undefined
              ? 'No Alpha in the vault reports this yet. Sync your Alphas, or re-check some on Alpha Types.'
              : `Vault average ${meta.rate ? fmt.pct(overall) : fmt.ratio(overall)} over ${fmt.int(page.data?.overallAlphas)} Alphas. “Vs vault” is the mean pulled toward that average, minus it.`}
          </p>
          {page.isError && <ErrorNotice error={page.error} title="Could not build scorecards" />}
        </div>
      </Panel>
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
        <Panel title={`${worse}: avoid`}>
          <DataTable
            label={`${worse} ${meta.label}`}
            rows={avoid}
            columns={cols}
            rowKey={(r) => r.name}
            loading={page.isPending}
            empty="No part has enough Alphas yet."
          />
        </Panel>
        <Panel title={`${better}: build more`}>
          <DataTable
            label={`${better} ${meta.label}`}
            rows={more}
            columns={cols}
            rowKey={(r) => r.name}
            loading={page.isPending}
            empty="No part has enough Alphas yet."
          />
        </Panel>
      </div>
    </Page>
  )
}
