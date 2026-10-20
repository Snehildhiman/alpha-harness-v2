/**
 * Repair: Alphas that failed only narrowly, and for each, hundreds of one-step variants ranked
 * by the models' chance of passing everything. Only the best few are simulated.
 */

import { useMutation, useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { HammerIcon, PlayIcon } from 'lucide-react'
import { useState } from 'react'
import { fmt } from '@/lib/format'
import {
  Badge,
  Button,
  Empty,
  ErrorNotice,
  LINK,
  Notice,
  Page,
  PageHeader,
  Panel,
  Segmented,
  Skeleton,
  signTone,
  TEXT_TONE,
} from '@/ui/kit'
import { type Column, DataTable } from '@/ui/table'
import {
  type NearMiss,
  nearMisses,
  queueRepair,
  type RepairKind,
  type RepairVariant,
  repairPlan,
} from './api'
import { PromotionsPanel } from './promotions'
import { TransplantsPanel } from './transplants'

const TABS: { value: RepairKind | 'all'; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'regular', label: 'Regular' },
  { value: 'ra', label: 'Region Agnostic' },
  { value: 'power_pool', label: 'Power Pool' },
  { value: 'theme', label: 'Current Theme' },
  { value: 'super', label: 'SuperAlpha' },
]

const KIND_LABEL: Record<string, string> = {
  regular: 'Regular',
  ra: 'RA',
  power_pool: 'Power Pool',
  theme: 'Theme',
  super: 'SuperAlpha',
}

const NEAR_COLUMNS: Column<NearMiss>[] = [
  {
    key: 'expression',
    header: 'Expression',
    width: 'minmax(240px,3fr)',
    cell: (r) => (
      <span className="truncate font-mono text-body-compact" title={r.expression ?? ''}>
        {r.expression ?? r.alphaId}
      </span>
    ),
  },
  { key: 'kind', header: 'Type', width: '96px', cell: (r) => KIND_LABEL[r.kind] ?? r.kind },
  { key: 'region', header: 'Region', width: '72px', cell: (r) => r.region ?? '—' },
  {
    key: 'sharpe',
    header: 'Sharpe',
    width: '72px',
    align: 'right',
    cell: (r) => (
      <span className={`num ${TEXT_TONE[signTone(r.sharpe)]}`}>{fmt.ratio(r.sharpe)}</span>
    ),
  },
  {
    key: 'failed',
    header: 'Fails by a little',
    width: 'minmax(220px,2fr)',
    cell: (r) => (
      <span className="flex min-w-0 flex-nowrap gap-1 overflow-hidden">
        {r.failed.slice(0, 2).map((i) => (
          <Badge key={i.name} tone="warn" className="shrink-0">
            {i.name.replaceAll('_', ' ').toLowerCase()} {fmt.ratio(i.value as number)} /{' '}
            {fmt.ratio(i.limit as number)}
          </Badge>
        ))}
      </span>
    ),
  },
]

const pct = (v: number | null | undefined) => fmt.pct(v, 0)

/** An RA variant's chance per region, best first: "USA 62 · EUR 48 · ASI 20". */
const REGIONS_COLUMN: Column<RepairVariant> = {
  key: 'regions',
  header: 'Each region passes',
  width: 'minmax(180px,1.2fr)',
  cell: (r) => (
    <span className="num truncate text-body-compact text-ink-muted">
      {Object.entries(r.regions ?? {})
        .sort((a, b) => b[1] - a[1])
        .map(([region, p]) => `${region} ${Math.round(p * 100)}`)
        .join(' · ')}
    </span>
  ),
}

const VARIANT_COLUMNS: Column<RepairVariant>[] = [
  {
    key: 'edit',
    header: 'Change',
    width: 'minmax(220px,1.6fr)',
    cell: (r) => <span className="truncate">{r.edit}</span>,
  },
  {
    key: 'expression',
    header: 'Expression',
    width: 'minmax(220px,2fr)',
    cell: (r) => (
      <span className="truncate font-mono text-body-compact" title={r.expression}>
        {r.expression.replaceAll('\n', ' ')}
      </span>
    ),
  },
  {
    key: 'settings',
    header: 'Neut · decay · trunc',
    width: '210px',
    cell: (r) => (
      <span className="num truncate whitespace-nowrap text-body-compact text-ink-subtle">
        {(r.neutralization ?? '—').toLowerCase()} · {r.decay ?? '—'} · {r.truncation ?? '—'}
      </span>
    ),
  },
  {
    key: 'p',
    header: 'Chance all pass',
    width: '120px',
    align: 'right',
    cell: (r) => (
      <span
        className={`num ${(r.pAll ?? 0) >= 0.5 ? 'text-pnl-positive-text' : (r.pAll ?? 0) < 0.2 ? 'text-ink-subtle' : ''}`}
      >
        {pct(r.pAll)}
      </span>
    ),
  },
  {
    key: 'corr',
    header: 'Predicted corr',
    width: '112px',
    align: 'right',
    cell: (r) => <span className="num">{fmt.ratio(r.correlation, 3)}</span>,
  },
  {
    key: 'sharpe',
    header: 'Predicted Sharpe',
    width: '120px',
    align: 'right',
    cell: (r) => <span className="num">{fmt.ratio(r.sharpe)}</span>,
  },
]

/** RA plans rank by the chance two regions pass, and show each region's chance. */
const RA_COLUMNS: Column<RepairVariant>[] = [
  ...VARIANT_COLUMNS.map((c) => (c.key === 'p' ? { ...c, header: 'Chance 2+ regions pass' } : c)),
  REGIONS_COLUMN,
]

function PlanPanel({ alphaId }: { alphaId: string }) {
  const plan = useQuery(repairPlan(alphaId))
  const [take, setTake] = useState(10)
  const queue = useMutation({ mutationFn: queueRepair })
  const data = plan.data
  return (
    <Panel
      title={`Variants of ${alphaId}`}
      actions={
        data && data.variants.length > 0 ? (
          <div className="flex items-center gap-2">
            <Segmented
              label="How many to simulate"
              items={[5, 10, 20].map((n) => ({ value: n, label: `Top ${n}` }))}
              value={take}
              onChange={setTake}
            />
            <Button
              variant="primary"
              loading={queue.isPending}
              onClick={() => queue.mutate({ alphaId, take })}
            >
              <PlayIcon aria-hidden />
              Simulate top {take}
            </Button>
          </div>
        ) : undefined
      }
    >
      <div className="flex flex-col gap-3">
        {plan.isPending && <Skeleton label="Generating and ranking variants" />}
        {plan.isError && <ErrorNotice error={plan.error} title="Could not plan a repair" />}
        {data?.problems.map((p) => (
          <Notice key={p} tone="warn" title="Cannot repair this Alpha">
            {p}
          </Notice>
        ))}
        {data && !data.ranked && (
          <Notice tone="warn" title="Not ranked yet">
            Train the models on the{' '}
            <Link to="/models" className={LINK}>
              Models
            </Link>{' '}
            screen and these variants will be ordered by their chance of passing.
          </Notice>
        )}
        {queue.isSuccess && (
          <Notice title={`Queued as task “${queue.data.name}”`}>
            Start it from{' '}
            <Link to="/tasks" className={LINK}>
              Tasks
            </Link>
            . Every result feeds the models, so the next repair ranks better.
          </Notice>
        )}
        {queue.isError && <ErrorNotice error={queue.error} title="Could not queue the repair" />}
        {data && data.variants.length > 0 && (
          <>
            <p className="text-body-compact text-ink-subtle">
              {fmt.int(data.generated)} variants generated
              {data.ranked ? ', best first by the models’ chance of passing every check' : ''}.
              Showing the top {fmt.int(data.variants.length)}.
            </p>
            {data.kind === 'ra' && (
              <p className="text-body-compact text-ink-subtle">
                Region agnostic: each variant is predicted in every region the family runs in, and
                ranked by the chance that at least two regions pass, which is what BRAIN needs.
              </p>
            )}
            <DataTable
              rows={data.variants}
              columns={data.kind === 'ra' ? RA_COLUMNS : VARIANT_COLUMNS}
              rowKey={(r) => r.id}
              label="Variants"
            />
          </>
        )}
      </div>
    </Panel>
  )
}

export function RepairScreen() {
  const [tab, setTab] = useState<RepairKind | 'all'>('all')
  const [picked, setPicked] = useState<string | null>(null)
  const list = useQuery(nearMisses(tab === 'all' ? null : tab))
  return (
    <Page>
      <PageHeader
        title="Repair"
        description="Alphas that failed only narrowly. Pick one: hundreds of one-step variants are ranked by the models, and only the best few are simulated."
      />
      <Panel
        title="Near-misses"
        actions={<Segmented label="Type" items={TABS} value={tab} onChange={(t) => setTab(t)} />}
      >
        {list.isError && <ErrorNotice error={list.error} title="Could not read near-misses" />}
        {list.data && list.data.length === 0 ? (
          <Empty icon={<HammerIcon />} title="No near-misses here">
            A near-miss fails only by a little: correlation within 0.05 of its limit, other checks
            within 10%.
          </Empty>
        ) : (
          <DataTable
            rows={list.data ?? []}
            columns={NEAR_COLUMNS}
            rowKey={(r) => r.alphaId}
            onRowClick={(r) => setPicked(r.alphaId)}
            rowClass={(r) => (r.alphaId === picked ? 'bg-surface-2' : undefined)}
            loading={list.isPending}
            maxHeight="40vh"
            label="Near-misses"
          />
        )}
      </Panel>
      {picked && <PlanPanel key={picked} alphaId={picked} />}
      <TransplantsPanel />
      <PromotionsPanel />
    </Page>
  )
}
