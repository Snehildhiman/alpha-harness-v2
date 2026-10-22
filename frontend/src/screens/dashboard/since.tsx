/** Since yesterday: what the last day (or week) brought, by alpha type. */

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useState } from 'react'
import type { components } from '@/api/generated'
import { http } from '@/api/http'
import { fmt } from '@/lib/format'
import { ErrorNotice, LINK, Metric, Panel, Segmented, Skeleton } from '@/ui/kit'

type Since = components['schemas']['Since']

const KIND_LABEL: Record<string, string> = {
  regular: 'Regular',
  ra: 'Region Agnostic',
  power_pool: 'Power Pool',
  theme: 'Current Theme',
  super: 'SuperAlpha',
}
const KIND_TAB: Record<string, 'regular' | 'ra' | 'power-pool' | 'theme' | 'super'> = {
  regular: 'regular',
  ra: 'ra',
  power_pool: 'power-pool',
  theme: 'theme',
  super: 'super',
}

export function SinceYesterday() {
  const [hours, setHours] = useState(24)
  const since = useQuery({
    queryKey: ['overview', 'since', hours],
    queryFn: () => http.get<Since>(`/api/overview/since?hours=${hours}`),
    staleTime: 60_000,
  })
  const data = since.data
  const sims = data?.simulations ?? {}
  const done = (sims['COMPLETE'] ?? 0) + (sims['WARNING'] ?? 0)
  const errored = (sims['ERROR'] ?? 0) + (sims['FAILED'] ?? 0)
  const reused = sims['SKIPPED'] ?? 0
  return (
    <Panel
      title={hours === 24 ? 'Since yesterday' : 'This week'}
      actions={
        <Segmented
          label="Period"
          items={[
            { value: 24, label: '24 h' },
            { value: 168, label: '7 days' },
          ]}
          value={hours}
          onChange={setHours}
        />
      }
    >
      {since.isPending && <Skeleton className="h-24 w-full" label="Reading what is new" />}
      {since.isError && <ErrorNotice error={since.error} title="Could not read what is new" />}
      {data && (
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <Metric boxed label="New alphas" value={fmt.int(data.new)} />
            <Metric
              boxed
              label="New submittable"
              value={fmt.int(data.submittable)}
              tone={data.submittable ? 'profit' : 'neutral'}
            />
            <Metric
              boxed
              label="New near-misses"
              value={fmt.int(data.nearMisses)}
              hint="On Repair"
            />
            <Metric
              boxed
              label="Simulated"
              value={fmt.int(done)}
              hint={`${fmt.int(errored)} errored`}
            />
            <Metric
              boxed
              label="Reused, not re-run"
              value={fmt.int(reused)}
              hint="Already simulated"
            />
          </div>
          {data.byKind.length > 0 && (
            <ul className="flex flex-wrap gap-x-6 gap-y-1 text-body-compact text-ink-muted">
              {data.byKind.map((k) => (
                <li key={k.kind}>
                  <Link
                    to="/types/$tab"
                    params={{ tab: KIND_TAB[k.kind] ?? 'regular' }}
                    className={LINK}
                  >
                    {KIND_LABEL[k.kind] ?? k.kind}
                  </Link>
                  : <span className="num">{fmt.int(k.new)}</span> new,{' '}
                  <span className="num">{fmt.int(k.submittable)}</span> submittable,{' '}
                  <span className="num">{fmt.int(k.nearMisses)}</span> near-misses
                </li>
              ))}
            </ul>
          )}
          {data.best.length > 0 && (
            <div className="flex flex-col gap-1">
              <span className="text-body-compact text-ink-subtle">Best new submittable</span>
              {data.best.map((a) => (
                <Link
                  key={a.alphaId}
                  to="/alpha/$alphaId"
                  params={{ alphaId: a.alphaId }}
                  className="flex gap-3 text-body-compact hover:text-ink"
                >
                  <span className="num w-24 text-ink">{a.alphaId}</span>
                  <span className="w-28 text-ink-subtle">
                    {KIND_LABEL[a.kind] ?? a.kind} · {a.region}
                  </span>
                  <span className="num w-24">Sharpe {fmt.ratio(a.sharpe)}</span>
                  <span className="truncate font-mono text-ink-muted">{a.expression}</span>
                </Link>
              ))}
            </div>
          )}
        </div>
      )}
    </Panel>
  )
}
