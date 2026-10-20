/**
 * Alpha Types: every stored Alpha on the tab of its type — regular, region-agnostic, Power
 * Pool, current-theme Power Pool, SuperAlpha — judged only by the checks that type answers to.
 * Regular, RA and SuperAlphas need prod correlation; Power Pool Alphas need Power Pool
 * correlation instead. A region-agnostic family is one row, submittable once two regions pass.
 */

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from '@tanstack/react-router'
import { RefreshCwIcon } from 'lucide-react'
import { useState } from 'react'
import { fmt } from '@/lib/format'
import { useRefetchOn } from '@/lib/ws'
import { DetailSheet } from '@/screens/pool/detail'
import { TYPE_TABS } from '@/shell/nav'
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
  signTone,
  TabBar,
  TabLink,
  TEXT_TONE,
} from '@/ui/kit'
import { type Column, DataTable, Pager } from '@/ui/table'
import {
  type Kind,
  recheck,
  type TabRow,
  type TypeSort,
  typeSummary,
  typeTab,
  type Verdict,
} from './api'
import { ThemeCalendar } from './themes'

const LIMIT = 100
/** Alphas one re-check takes on, best Sharpe first: `/check` is slow and rate-limited. */
const RECHECK_LIMIT = 50

const KIND_OF_TAB: Record<string, Kind> = {
  regular: 'regular',
  ra: 'ra',
  'power-pool': 'power_pool',
  theme: 'theme',
  super: 'super',
}

const VERDICTS: { value: Verdict; label: string }[] = [
  { value: 'submittable', label: 'Submittable' },
  { value: 'recheck', label: 'Needs re-check' },
  { value: 'pending', label: 'Checks pending' },
  { value: 'refused', label: 'Failing' },
  { value: 'submitted', label: 'Submitted' },
]

const SORTS: { value: TypeSort; label: string }[] = [
  { value: 'sharpe', label: 'Sharpe' },
  { value: 'fitness', label: 'Fitness' },
  { value: 'turnover', label: 'Turnover' },
  { value: 'date_created', label: 'Newest' },
]

/** What each tab is judged by, said once above its table. */
const RULES: Record<Kind, string> = {
  regular: 'Standard checks, self-correlation and prod correlation (below 0.7, or BRAIN’s PASS).',
  ra: 'One row per family. Submittable once at least two regions pass the regular rules, prod correlation included.',
  power_pool:
    'Standard checks, self-correlation and Power Pool correlation. Prod correlation does not apply.',
  theme: 'Power Pool rules, plus BRAIN’s theme match for the theme running now.',
  super: 'The SuperAlpha’s own checks, self-correlation and prod correlation.',
}

function Why({ row }: { row: TabRow }) {
  if (row.verdict === 'submittable' || row.verdict === 'submitted') {
    return <span className="text-ink-subtle">—</span>
  }
  const failed = row.failed.slice(0, 2)
  const more = row.failed.length - failed.length
  return (
    <span className="flex min-w-0 flex-nowrap items-center gap-1 overflow-hidden">
      {failed.map((issue) => (
        <Badge
          key={issue.name}
          tone="loss"
          className="shrink-0"
          title={
            typeof issue.value === 'number' && typeof issue.limit === 'number'
              ? `${issue.name}: ${issue.value} vs limit ${issue.limit}`
              : `${issue.name}: ${issue.result}`
          }
        >
          {issue.name.replaceAll('_', ' ').toLowerCase()}
          {typeof issue.value === 'number' ? ` ${fmt.ratio(issue.value)}` : ''}
        </Badge>
      ))}
      {more > 0 && <span className="text-body-compact text-ink-subtle">+{more}</span>}
      {row.failed.length === 0 && row.pending.length > 0 && (
        <span className="text-body-compact text-ink-subtle">
          waiting on {row.pending.slice(0, 2).join(', ').replaceAll('_', ' ').toLowerCase()}
          {row.pending.length > 2 ? ` +${row.pending.length - 2}` : ''}
        </span>
      )}
    </span>
  )
}

function regions(row: TabRow) {
  if (row.kind !== 'ra') return row.region ?? '—'
  return `${row.regionsPassing.length}/${row.regionsTried.length} pass${
    row.regionsPassing.length ? ` (${row.regionsPassing.join(', ')})` : ''
  }`
}

const COLUMNS: Column<TabRow>[] = [
  {
    key: 'expression',
    header: 'Expression',
    width: 'minmax(260px,3fr)',
    cell: (r) => (
      <span className="truncate font-mono text-body-compact" title={r.expression ?? ''}>
        {r.expression ?? r.alphaId}
      </span>
    ),
  },
  { key: 'region', header: 'Region', width: 'minmax(170px,1.2fr)', cell: regions },
  {
    key: 'sharpe',
    header: 'Sharpe',
    width: '80px',
    align: 'right',
    cell: (r) => (
      <span className={`num ${TEXT_TONE[signTone(r.sharpe)]}`}>{fmt.ratio(r.sharpe)}</span>
    ),
  },
  {
    key: 'fitness',
    header: 'Fitness',
    width: '80px',
    align: 'right',
    cell: (r) => <span className="num">{fmt.ratio(r.fitness)}</span>,
  },
  {
    key: 'turnover',
    header: 'Turnover',
    width: '88px',
    align: 'right',
    cell: (r) => <span className="num">{fmt.pct(r.turnover)}</span>,
  },
  {
    key: 'checked',
    header: 'Checked',
    width: '92px',
    align: 'right',
    cell: (r) => (
      <span className="text-body-compact text-ink-subtle" title={r.checkedAt ?? ''}>
        {fmt.ago(r.checkedAt)}
      </span>
    ),
  },
  { key: 'why', header: 'What stops it', width: 'minmax(220px,2fr)', cell: (r) => <Why row={r} /> },
]

/** Power Pool tabs add how today's theme reads each Alpha. */
/** Prod-correlation tabs add the local floor: the least prod correlation the Alpha can have,
 *  from its correlation with Alphas whose prod correlation BRAIN already reported. */
const FLOOR_COLUMN: Column<TabRow> = {
  key: 'floor',
  header: 'Prod floor',
  width: '112px',
  align: 'right',
  cell: (r) => {
    // Below zero the landmarks imply nothing about it.
    if (r.crowdFloor === null || r.crowdFloor === undefined || r.crowdFloor < 0) {
      return <span className="text-ink-subtle">—</span>
    }
    const tone = r.crowdFloor >= 0.7 ? 'loss' : r.crowdFloor >= 0.6 ? 'warn' : 'muted'
    return (
      <span
        className={`num ${TEXT_TONE[tone]}`}
        title={`At least ${fmt.ratio(r.crowdFloor)}: correlates ${fmt.ratio(r.crowdR)} with ${r.crowdVia ?? '?'}, whose prod correlation is ${fmt.ratio(r.crowdP)}.${r.crowdFloor >= 0.7 ? ' Re-check skips it.' : ''}`}
      >
        ≥ {fmt.ratio(r.crowdFloor)}
      </span>
    )
  },
}

const THEME_COLUMN: Column<TabRow> = {
  key: 'theme',
  header: 'Today’s theme',
  width: 'minmax(200px,1.6fr)',
  cell: (r) => (
    <span
      className={`truncate text-body-compact ${r.kind === 'theme' ? 'text-pnl-positive-text' : 'text-ink-subtle'}`}
      title={r.themeNote ?? ''}
    >
      {r.kind === 'theme' && !r.themeNote?.startsWith('BRAIN')
        ? `fits · ${r.themeNote ?? ''}`
        : (r.themeNote ?? '—')}
    </span>
  ),
}

export function TypesScreen() {
  const { tab } = useParams({ from: '/types/$tab' })
  const kind = KIND_OF_TAB[tab]
  const [verdict, setVerdict] = useState<Verdict>('submittable')
  const [sort, setSort] = useState<TypeSort>('sharpe')
  const [offset, setOffset] = useState(0)
  const [detailId, setDetailId] = useState<string | null>(null)

  const summary = useQuery(typeSummary)
  const client = useQueryClient()
  // A re-check writes fresh checks as each answer lands; follow it while it runs.
  useRefetchOn('tasks', ['separation'], 4000)
  const rechecking = useMutation({
    mutationFn: () => recheck({ tab: kind ?? 'regular', verdict, limit: RECHECK_LIMIT }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ['separation'] }),
  })
  const page = useQuery({
    ...typeTab({ tab: kind ?? 'regular', verdict, sort, limit: LIMIT, offset }),
    enabled: kind !== undefined,
    placeholderData: keepPreviousData,
  })
  const counts = kind ? summary.data?.counts[kind] : undefined
  const columns =
    kind === 'power_pool' || kind === 'theme'
      ? [...COLUMNS, THEME_COLUMN]
      : [...COLUMNS, FLOOR_COLUMN]
  const running = summary.data?.theme

  return (
    <Page>
      <PageHeader
        title="Alpha Types"
        description="Each Alpha on its type’s tab, judged only by the checks that type has to pass."
      />
      <TabBar>
        {TYPE_TABS.map((t) => {
          const k = KIND_OF_TAB[t.tab]
          const c = k ? summary.data?.counts[k] : undefined
          // Candidates: submittable now, or once a re-check confirms them.
          const n = c ? (c['submittable'] ?? 0) + (c['recheck'] ?? 0) : undefined
          return (
            <TabLink key={t.tab} to="/types/$tab" params={{ tab: t.tab }}>
              {t.label}
              {n !== undefined && <span className="num ml-1.5 text-ink-subtle">{fmt.int(n)}</span>}
            </TabLink>
          )
        })}
      </TabBar>
      {kind === undefined ? (
        <Panel>
          <Empty title={`No tab called “${tab}”`}>
            <Link to="/types/$tab" params={{ tab: TYPE_TABS[0].tab }} className={LINK}>
              Go to {TYPE_TABS[0].label}
            </Link>
          </Empty>
        </Panel>
      ) : (
        <>
          {kind === 'theme' && (
            <Panel>
              <div className="flex flex-col gap-3">
                {running ? (
                  <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
                    <span className="text-title font-medium">{running.name}</span>
                    <span className="num text-body-compact text-ink-muted">{running.rule}</span>
                    <span className="text-body-compact text-ink-subtle">
                      {fmt.date(running.start)} – {fmt.date(running.end)}
                    </span>
                  </div>
                ) : (
                  <p className="text-body text-ink-subtle">
                    No theme is running today. Add the current one to the calendar below.
                  </p>
                )}
                <ThemeCalendar />
              </div>
            </Panel>
          )}
          <Panel
            title={RULES[kind]}
            actions={
              <Segmented
                label="Sort by"
                items={SORTS}
                value={sort}
                onChange={(s) => {
                  setSort(s)
                  setOffset(0)
                }}
              />
            }
          >
            <div className="flex flex-col gap-3">
              <Segmented
                label="Show"
                items={VERDICTS.map((v) => ({
                  value: v.value,
                  label: (
                    <>
                      {v.label}
                      {counts && (
                        <span className="num ml-1.5 text-ink-subtle">
                          {fmt.int(counts[v.value])}
                        </span>
                      )}
                    </>
                  ),
                }))}
                value={verdict}
                onChange={(v) => {
                  setVerdict(v)
                  setOffset(0)
                }}
              />
              {(verdict === 'recheck' || verdict === 'submittable') && (
                <Notice
                  title={
                    verdict === 'recheck'
                      ? 'These passed, but their correlation results are old'
                      : 'Re-check right before you submit'
                  }
                  action={
                    <Button
                      variant={verdict === 'recheck' ? 'primary' : 'secondary'}
                      loading={rechecking.isPending}
                      disabled={!page.data?.total}
                      onClick={() => rechecking.mutate()}
                    >
                      <RefreshCwIcon aria-hidden />
                      Re-check top {fmt.int(Math.min(RECHECK_LIMIT, page.data?.total ?? 0))}
                    </Button>
                  }
                >
                  Prod and Power Pool correlation rise as others submit. Re-checking asks BRAIN to
                  run the submission checks again (no simulations, nothing submitted), and each
                  Alpha moves to the right list as its answer lands. Alphas whose prod floor is
                  already 0.7 or more are skipped: they cannot pass.
                  {rechecking.isSuccess &&
                    ` Re-checking ${fmt.int(rechecking.data.alphas)} Alphas in the background.`}
                </Notice>
              )}
              {rechecking.isError && (
                <ErrorNotice error={rechecking.error} title="Could not start the re-check" />
              )}
              {(summary.isError || page.isError) && (
                <ErrorNotice
                  error={summary.error ?? page.error}
                  title="Could not judge the vault"
                />
              )}
              <DataTable
                label={`${tab} alphas`}
                rows={page.data?.rows ?? []}
                columns={columns}
                rowKey={(r) => r.alphaId}
                onRowClick={(r) => setDetailId(r.children[0] ?? r.alphaId)}
                loading={page.isPending}
                empty="No Alphas here yet. Sync your Alphas from the Alphas screen to fill these tabs."
              />
              <Pager
                total={page.data?.total ?? 0}
                offset={offset}
                limit={LIMIT}
                onChange={setOffset}
              />
            </div>
          </Panel>
        </>
      )}
      <DetailSheet alphaId={detailId} onClose={() => setDetailId(null)} />
    </Page>
  )
}
