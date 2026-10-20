/**
 * Crowding: which datasets and fields other researchers are piling into, from the daily
 * catalog snapshots. BRAIN publishes every field's alpha and user counts; a snapshot a day
 * turns those into growth, which is the crowd moving. Fast growth means prod correlation
 * there is rising; quiet, large datasets are where room is left.
 */

import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { UsersIcon } from 'lucide-react'
import { useState } from 'react'
import { fmt } from '@/lib/format'
import { useScope } from '@/lib/scope'
import { Empty, ErrorNotice, Page, PageHeader, Panel, Segmented } from '@/ui/kit'
import { ScopePicker } from '@/ui/scope-picker'
import { type Column, DataTable } from '@/ui/table'
import { type DatasetTrend, datasetTrends, type FieldTrend, fieldTrends, snapshotDays } from './api'

const WINDOWS = [
  { value: 1, label: '1 day' },
  { value: 7, label: '7 days' },
  { value: 30, label: '30 days' },
]

const growth = (v: number | null | undefined) =>
  v == null ? '—' : v > 0 ? `+${fmt.int(v)}` : fmt.int(v)

const DATASET_COLUMNS: Column<DatasetTrend>[] = [
  {
    key: 'dataset',
    header: 'Dataset',
    width: 'minmax(200px,2fr)',
    cell: (r) => <span className="truncate font-mono text-body-compact">{r.datasetId}</span>,
  },
  {
    key: 'alphas',
    header: 'Alphas',
    width: '96px',
    align: 'right',
    cell: (r) => <span className="num">{fmt.int(r.alphaCount)}</span>,
  },
  {
    key: 'users',
    header: 'Users',
    width: '80px',
    align: 'right',
    cell: (r) => <span className="num">{fmt.int(r.userCount)}</span>,
  },
  {
    key: 'growth',
    header: 'New alphas',
    width: '104px',
    align: 'right',
    cell: (r) => <span className="num">{growth(r.alphaGrowth)}</span>,
  },
  {
    key: 'per-day',
    header: 'Per day',
    width: '88px',
    align: 'right',
    cell: (r) => <span className="num">{fmt.ratio(r.alphaGrowthPerDay, 1)}</span>,
  },
  {
    key: 'new-users',
    header: 'New users',
    width: '96px',
    align: 'right',
    cell: (r) => <span className="num">{growth(r.userGrowth)}</span>,
  },
  {
    key: 'fields',
    header: 'Fields',
    width: '72px',
    align: 'right',
    cell: (r) => <span className="num">{fmt.int(r.fieldCount)}</span>,
  },
  {
    key: 'pyramid',
    header: 'Pyramid ×',
    width: '88px',
    align: 'right',
    cell: (r) => <span className="num">{fmt.ratio(r.pyramidMultiplier, 1)}</span>,
  },
]

const FIELD_COLUMNS: Column<FieldTrend>[] = [
  {
    key: 'field',
    header: 'Field',
    width: 'minmax(220px,2fr)',
    cell: (r) => <span className="truncate font-mono text-body-compact">{r.fieldId}</span>,
  },
  {
    key: 'alphas',
    header: 'Alphas',
    width: '96px',
    align: 'right',
    cell: (r) => <span className="num">{fmt.int(r.alphaCount)}</span>,
  },
  {
    key: 'users',
    header: 'Users',
    width: '80px',
    align: 'right',
    cell: (r) => <span className="num">{fmt.int(r.userCount)}</span>,
  },
  {
    key: 'growth',
    header: 'New alphas',
    width: '104px',
    align: 'right',
    cell: (r) => <span className="num">{growth(r.alphaGrowth)}</span>,
  },
  {
    key: 'new-users',
    header: 'New users',
    width: '96px',
    align: 'right',
    cell: (r) => <span className="num">{growth(r.userGrowth)}</span>,
  },
]

export function CrowdingScreen() {
  const [scope, setScope] = useScope('crowding')
  const [days, setDays] = useState(7)
  const [dataset, setDataset] = useState<string | null>(null)
  const market = { region: scope.region, delay: scope.delay, universe: scope.universe, days }
  const history = useQuery(snapshotDays)
  const sets = useQuery({ ...datasetTrends(market), placeholderData: keepPreviousData })
  const fields = useQuery({ ...fieldTrends(market, dataset), placeholderData: keepPreviousData })
  const snapshots = history.data?.length ?? 0
  return (
    <Page>
      <PageHeader
        title="Crowding"
        description="Where other researchers are piling in, from the catalog's daily snapshots of every field's alpha and user counts. Fast growth means prod correlation there is rising; large, quiet datasets are where room is left."
      />
      <Panel
        title="Datasets, fastest-growing first"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <ScopePicker
              scope={scope}
              onChange={(change) => {
                setScope(change)
                setDataset(null)
              }}
            />
            <Segmented label="Window" items={WINDOWS} value={days} onChange={setDays} />
          </div>
        }
      >
        <div className="flex flex-col gap-3">
          <p className="text-body-compact text-ink-subtle">
            {snapshots
              ? `${fmt.int(snapshots)} daily snapshot${snapshots === 1 ? '' : 's'} so far${snapshots < 2 ? '; growth shows from the second' : ''}. Pick a dataset to see its fields.`
              : 'No snapshot yet: the daily catalog sync makes one each morning (Settings → daily sync).'}
          </p>
          {sets.isError && <ErrorNotice error={sets.error} title="Could not read the history" />}
          {sets.data && sets.data.length === 0 ? (
            <Empty icon={<UsersIcon />} title="Nothing for this market yet">
              Download it on the Sync screen; the daily sync then snapshots it every morning.
            </Empty>
          ) : (
            <DataTable
              rows={sets.data ?? []}
              columns={DATASET_COLUMNS}
              rowKey={(r) => r.datasetId}
              onRowClick={(r) => setDataset(r.datasetId)}
              rowClass={(r) => (r.datasetId === dataset ? 'bg-surface-2' : undefined)}
              loading={sets.isPending}
              maxHeight="45vh"
              label="Datasets"
            />
          )}
        </div>
      </Panel>
      {dataset && (
        <Panel title={`Fields of ${dataset}`}>
          {fields.isError && <ErrorNotice error={fields.error} title="Could not read the fields" />}
          <DataTable
            rows={fields.data ?? []}
            columns={FIELD_COLUMNS}
            rowKey={(r) => r.fieldId}
            loading={fields.isPending}
            maxHeight="45vh"
            label="Fields"
          />
        </Panel>
      )}
    </Page>
  )
}
