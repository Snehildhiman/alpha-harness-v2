/**
 * Transplants: passing regular Alphas, each tried in the downloaded regions it has not run
 * in. Prod correlation is measured against each region's own crowd, and an expression that
 * passes in two regions is an all-region Alpha.
 */

import { useMutation, useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { GlobeIcon, PlayIcon } from 'lucide-react'
import { useState } from 'react'
import { fmt } from '@/lib/format'
import { Button, Empty, ErrorNotice, LINK, Notice, Panel, Segmented } from '@/ui/kit'
import { type Column, DataTable } from '@/ui/table'
import { queueTransplants, type TransplantRow, transplantPlan } from './api'

const COLUMNS: Column<TransplantRow>[] = [
  {
    key: 'expression',
    header: 'Expression',
    width: 'minmax(240px,3fr)',
    cell: (r) => (
      <span className="truncate font-mono text-body-compact" title={r.expression}>
        {r.expression.replaceAll('\n', ' ')}
      </span>
    ),
  },
  {
    key: 'from',
    header: 'From',
    width: '200px',
    cell: (r) => (
      <span className="truncate text-body-compact text-ink-muted" title={r.sourceId}>
        {r.origin} · {r.sourceVerdict === 'recheck' ? 're-check' : r.sourceVerdict}
      </span>
    ),
  },
  {
    key: 'to',
    header: 'Into',
    width: '130px',
    cell: (r) => (
      <span className="truncate">
        {r.region} {r.universe}
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
        {fmt.pct(r.pAll, 0)}
      </span>
    ),
  },
  {
    key: 'corr',
    header: 'Predicted prod corr',
    width: '140px',
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

export function TransplantsPanel() {
  const [region, setRegion] = useState<string>('all')
  const [take, setTake] = useState(20)
  const plan = useQuery(transplantPlan(region === 'all' ? null : region))
  const queue = useMutation({ mutationFn: queueTransplants })
  const data = plan.data
  const regions = [...new Set((data?.markets ?? []).map((m) => m.split(' ')[0] ?? m))]
  return (
    <Panel
      title="Transplants into other regions"
      actions={
        <div className="flex flex-wrap items-center gap-2">
          {regions.length > 1 && (
            <Segmented
              label="Into"
              items={[
                { value: 'all', label: 'Any region' },
                ...regions.map((r) => ({ value: r, label: r })),
              ]}
              value={region}
              onChange={setRegion}
            />
          )}
          {data && data.transplants.length > 0 && (
            <>
              <Segmented
                label="How many to simulate"
                items={[10, 20, 40].map((n) => ({ value: n, label: `Top ${n}` }))}
                value={take}
                onChange={setTake}
              />
              <Button
                variant="primary"
                loading={queue.isPending}
                onClick={() => queue.mutate({ take, region: region === 'all' ? null : region })}
              >
                <PlayIcon aria-hidden />
                Simulate top {take}
              </Button>
            </>
          )}
        </div>
      }
    >
      <div className="flex flex-col gap-3">
        <p className="text-body-compact text-ink-subtle">
          Your passing regular Alphas, each in the downloaded regions it has not run in, at the same
          settings and a universe of the same size. Prod correlation there is measured against that
          region’s crowd, and an expression that passes in two regions is an all-region Alpha.
        </p>
        {plan.isError && <ErrorNotice error={plan.error} title="Could not find transplants" />}
        {data && !data.ranked && (
          <Notice tone="warn" title="Not ranked yet">
            Train the models on the{' '}
            <Link to="/models" className={LINK}>
              Models
            </Link>{' '}
            screen and these will be ordered by their chance of passing.
          </Notice>
        )}
        {queue.isSuccess && (
          <Notice title={`Queued as task “${queue.data.name}”`}>
            Start it from{' '}
            <Link to="/tasks" className={LINK}>
              Tasks
            </Link>
            .
          </Notice>
        )}
        {queue.isError && (
          <ErrorNotice error={queue.error} title="Could not queue the transplants" />
        )}
        {data && data.transplants.length === 0 ? (
          <Empty icon={<GlobeIcon />} title="Nothing to transplant">
            Every passing Alpha has run in every downloaded region that carries its fields. Download
            more markets on the Sync screen.
          </Empty>
        ) : (
          <>
            {data && (
              <p className="text-body-compact text-ink-subtle">
                {fmt.int(data.found)} transplants found; showing the best{' '}
                {fmt.int(data.transplants.length)}.
              </p>
            )}
            <DataTable
              rows={data?.transplants ?? []}
              columns={COLUMNS}
              rowKey={(r) => r.id}
              loading={plan.isPending}
              maxHeight="50vh"
              label="Transplants"
            />
          </>
        )}
      </div>
    </Panel>
  )
}
