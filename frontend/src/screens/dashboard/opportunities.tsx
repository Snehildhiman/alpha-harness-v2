/**
 * Today's openings: what can be submitted now in each type, what needs a re-check first, and
 * where more is waiting (near-misses to repair, transplants into other regions).
 */

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { http } from '@/api/http'
import { fmt } from '@/lib/format'
import { nearMisses, type TransplantPlan } from '@/screens/repair/api'
import { typeSummary } from '@/screens/types/api'
import { TYPE_TABS } from '@/shell/nav'
import { Button, ErrorNotice, Panel, Skeleton } from '@/ui/kit'

const KIND: Record<(typeof TYPE_TABS)[number]['tab'], string> = {
  regular: 'regular',
  ra: 'ra',
  'power-pool': 'power_pool',
  theme: 'theme',
  super: 'super',
}

export function Opportunities() {
  const summary = useQuery(typeSummary)
  const near = useQuery(nearMisses(null))
  // A count only: scoring every transplant is the Repair screen's job, not the Dashboard's.
  const transplants = useQuery({
    queryKey: ['repair', 'transplants', 'count'],
    queryFn: () => http.get<TransplantPlan>('/api/repair/transplants?count=true&limit=1'),
    staleTime: 5 * 60_000,
  })
  const counts = summary.data?.counts ?? {}
  return (
    <Panel
      title="Today’s Openings"
      description="Your daily routine, left to right: find, fix, re-check, submit."
      actions={
        <div className="flex flex-wrap gap-2">
          <Button size="sm" render={<Link to="/labs" />}>
            1 · Find
          </Button>
          <Button size="sm" render={<Link to="/repair" />}>
            2 · Fix
          </Button>
          <Button size="sm" render={<Link to="/types/$tab" params={{ tab: 'regular' }} />}>
            3 · Re-check
          </Button>
          <Button
            size="sm"
            variant="primary"
            render={<Link to="/types/$tab" params={{ tab: 'regular' }} />}
          >
            4 · Submit
          </Button>
        </div>
      }
    >
      {summary.isError ? (
        <ErrorNotice error={summary.error} title="Could not judge the vault" />
      ) : summary.isPending ? (
        <Skeleton label="Judging your Alphas" />
      ) : (
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            {TYPE_TABS.map((t) => {
              const c = counts[KIND[t.tab]] ?? {}
              return (
                <Link
                  key={t.tab}
                  to="/types/$tab"
                  params={{ tab: t.tab }}
                  className="flex flex-col gap-1 rounded-md border border-hairline-subtle p-3 hover:bg-surface-2"
                >
                  <span className="text-caption font-medium uppercase tracking-wide text-ink-subtle">
                    {t.label}
                  </span>
                  <span className="num text-title text-ink">{fmt.int(c['submittable'] ?? 0)}</span>
                  <span className="text-body-compact text-ink-subtle">
                    submittable · <span className="num">{fmt.int(c['recheck'] ?? 0)}</span> to
                    re-check
                  </span>
                </Link>
              )
            })}
          </div>
          {summary.data?.theme && (
            <p className="text-body-compact text-ink-subtle">
              Running theme: {summary.data.theme.name} — {summary.data.theme.rule}
            </p>
          )}
          <p className="text-body text-ink-muted">
            <Link to="/repair" className="underline-offset-2 hover:underline">
              <span className="num">
                {near.data
                  ? `${fmt.int(near.data.length)}${near.data.length >= 200 ? '+' : ''}`
                  : '…'}
              </span>{' '}
              near-misses to repair
            </Link>
            {' · '}
            <Link to="/repair" className="underline-offset-2 hover:underline">
              <span className="num">
                {transplants.data ? fmt.int(transplants.data.found) : '…'}
              </span>{' '}
              transplants into other regions
            </Link>
          </p>
        </div>
      )}
    </Panel>
  )
}
