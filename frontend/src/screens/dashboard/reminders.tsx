/**
 * Submission reminder: alphas that passed Check now two or more days ago and are still not
 * submitted. Correlations only drift up, so the pass grows stale: check again, then submit.
 */

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import type { components } from '@/api/generated'
import { http } from '@/api/http'
import { fmt } from '@/lib/format'
import { LINK, Notice } from '@/ui/kit'

type Reminder = components['schemas']['Reminder']

export function SubmitReminders() {
  const found = useQuery({
    queryKey: ['overview', 'reminders'],
    queryFn: () => http.get<Reminder[]>('/api/overview/reminders'),
    staleTime: 5 * 60_000,
  })
  const rows = found.data ?? []
  if (rows.length === 0) return null
  return (
    <Notice
      tone="warn"
      title={`${rows.length} alpha${rows.length > 1 ? 's' : ''} passed Check now 2+ days ago and ${rows.length > 1 ? 'are' : 'is'} still not submitted`}
    >
      <p className="mb-2 text-body-compact text-pretty">
        Correlations only drift up, so a pass grows stale. Press Check now again on Alpha Types,
        then submit on BRAIN if it still passes.
      </p>
      <ul className="flex flex-col gap-1">
        {rows.slice(0, 8).map((r) => (
          <li key={r.alphaId} className="flex flex-wrap gap-3 text-body-compact">
            <Link to="/alpha/$alphaId" params={{ alphaId: r.alphaId }} className={`num ${LINK}`}>
              {r.alphaId}
            </Link>
            <span className="text-ink-subtle">
              {r.region} · Sharpe {fmt.ratio(r.sharpe)} · checked {fmt.int(r.days)} days ago
            </span>
            <a href={r.link} target="_blank" rel="noreferrer" className={LINK}>
              Open on BRAIN
            </a>
          </li>
        ))}
      </ul>
    </Notice>
  )
}
