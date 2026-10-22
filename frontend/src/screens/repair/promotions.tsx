/**
 * Promotions: expressions that already pass as regular Alphas in two or more of BRAIN's
 * region-agnostic markets, run once as a region-agnostic Alpha. BRAIN takes the family when
 * two of its regions pass, and these have shown they can.
 */

import { useMutation, useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { GlobeIcon, PlayIcon } from 'lucide-react'
import { useState } from 'react'
import { fmt } from '@/lib/format'
import { Button, Empty, ErrorNotice, LINK, Notice, Panel, Segmented } from '@/ui/kit'
import { type Column, DataTable } from '@/ui/table'
import { type PromotionRow, type PromotionSource, promotionPlan, queuePromotions } from './api'

const COLUMNS: Column<PromotionRow>[] = [
  {
    key: 'expression',
    header: 'Expression',
    width: 'minmax(260px,3fr)',
    cell: (r) => (
      <span className="truncate font-mono text-body-compact" title={r.expression}>
        {r.expression.replaceAll('\n', ' ')}
      </span>
    ),
  },
  {
    key: 'regions',
    header: 'Passes in',
    width: 'minmax(180px,1.2fr)',
    cell: (r) => (
      <span
        className="truncate"
        title={Object.entries(r.regions)
          .map(([region, id]) => `${region}: ${id}`)
          .join(', ')}
      >
        {Object.keys(r.regions).join(' · ')}
      </span>
    ),
  },
  { key: 'delay', header: 'Delay', width: '64px', align: 'right', cell: (r) => r.delay },
  {
    key: 'settings',
    header: 'Neut · decay · trunc',
    width: '200px',
    cell: (r) => (
      <span className="num truncate text-body-compact text-ink-subtle">
        {(r.neutralization ?? '—').toLowerCase()} · {r.decay ?? '—'} · {r.truncation ?? '—'}
      </span>
    ),
  },
  {
    key: 'sharpe',
    header: 'Mean Sharpe',
    width: '104px',
    align: 'right',
    cell: (r) => <span className="num">{fmt.ratio(r.sharpe)}</span>,
  },
]

export function PromotionsPanel() {
  const [source, setSource] = useState<PromotionSource>('regions')
  const plan = useQuery(promotionPlan(source))
  const queue = useMutation({ mutationFn: queuePromotions })
  const [delay, setDelay] = useState(1)
  const [picked, setPicked] = useState<string | null>(null)
  const [take, setTake] = useState(20)
  const data = plan.data
  const rows = (data?.promotions ?? []).filter((p) => p.delay === delay)
  const universes = data?.universes[delay] ?? []
  const universe = picked && universes.includes(picked) ? picked : (universes[0] ?? null)
  const delays = [...new Set((data?.promotions ?? []).map((p) => p.delay))].sort()
  return (
    <Panel
      title="Promote to region agnostic"
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <Segmented
            label="From"
            items={[
              { value: 'regions' as const, label: 'Pass in 2 regions' },
              { value: 'glb' as const, label: 'Global alphas' },
            ]}
            value={source}
            onChange={setSource}
          />
          {delays.length > 1 && (
            <Segmented
              label="Delay"
              items={delays.map((d) => ({ value: d, label: `D${d}` }))}
              value={delay}
              onChange={setDelay}
            />
          )}
          {universes.length > 0 && (
            <Segmented
              label="Universe"
              items={universes.map((u) => ({ value: u, label: u }))}
              value={universe ?? ''}
              onChange={setPicked}
            />
          )}
          {rows.length > 0 && universe && (
            <>
              <Segmented
                label="How many to simulate"
                items={[10, 20, 50].map((n) => ({ value: n, label: `Top ${n}` }))}
                value={take}
                onChange={setTake}
              />
              <Button
                variant="primary"
                loading={queue.isPending}
                onClick={() => queue.mutate({ universe, delay, take, source })}
              >
                <PlayIcon aria-hidden />
                Run top {Math.min(take, rows.length)} as RA
              </Button>
            </>
          )}
        </div>
      }
    >
      <div className="flex flex-col gap-3">
        <p className="text-body-compact text-ink-subtle">
          {source === 'glb'
            ? 'Your passing and submitted Global alphas at delay 1 that never ran as region-agnostic: the ARC webinar’s easiest start, since a Global signal already spans markets and currencies. Each runs once as an RA alpha; BRAIN takes it once two regions pass.'
            : 'Expressions that already pass as regular Alphas in two or more of USA, EUR, ASI and GLB and have never run as a region-agnostic Alpha. BRAIN takes a family once two of its regions pass.'}
        </p>
        {plan.isError && <ErrorNotice error={plan.error} title="Could not find promotions" />}
        {data && universes.length === 0 && (
          <Notice tone="warn" title="Region-agnostic market not downloaded">
            Download region ALL on the{' '}
            <Link to="/sync" className={LINK}>
              Sync
            </Link>{' '}
            screen to choose a universe.
          </Notice>
        )}
        {queue.isSuccess && (
          <Notice title={`Started task “${queue.data.name}”`}>
            It is running; watch it on{' '}
            <Link to="/tasks" className={LINK}>
              Tasks
            </Link>
            .
          </Notice>
        )}
        {queue.isError && <ErrorNotice error={queue.error} title="Could not queue the families" />}
        {data && rows.length === 0 ? (
          <Empty icon={<GlobeIcon />} title="Nothing to promote yet">
            Transplant passing Alphas into other regions first: every one that passes in a second
            market shows up here.
          </Empty>
        ) : (
          <DataTable
            rows={rows}
            columns={COLUMNS}
            rowKey={(r) => r.id}
            loading={plan.isPending}
            maxHeight="40vh"
            label="Promotions"
          />
        )}
      </div>
    </Panel>
  )
}
