/**
 * What a task's failed simulations have in common. When BRAIN fails one kind of request every
 * time (a neutralization, a universe, an operator), that value sits at the top, every Alpha
 * sent with it failed, which says what to leave out of the next task.
 */

import { useQuery } from '@tanstack/react-query'
import type { components } from '@/api/generated'
import { http } from '@/api/http'
import { fmt } from '@/lib/format'
import { Disclosure, ErrorNotice, Skeleton } from '@/ui/kit'

type Pattern = components['schemas']['FailurePattern']

export function FailurePattern({ taskId, failed }: { taskId: number; failed: number }) {
  const pattern = useQuery({
    queryKey: ['lab-tasks', 'failure-pattern', taskId, failed],
    queryFn: () => http.get<Pattern>(`/api/lab-tasks/${taskId}/failure-pattern`),
  })
  const data = pattern.data
  const always = (data?.slices ?? []).filter((s) => s.failed === s.sent && s.sent >= 3)
  return (
    <Disclosure summary="What the failed ones have in common">
      <div className="flex flex-col gap-3">
        {pattern.isPending && <Skeleton label="Comparing the failed simulations" />}
        {pattern.isError && <ErrorNotice error={pattern.error} title="Could not compare them" />}
        {data && (
          <>
            <p className="text-body-compact text-pretty text-ink-subtle">
              {fmt.int(data.failed)} of {fmt.int(data.sent)} back failed.{' '}
              {data.failed === data.sent
                ? 'Every one failed, so look at what they all share: the settings below that apply to all of them are the suspects, and a task without one of them shows which.'
                : always.length
                  ? `Every Alpha sent with ${always.map((s) => `${s.attribute.toLowerCase()} ${s.value}`).join(', ')} failed: leave ${always.length === 1 ? 'it' : 'them'} out of the next task.`
                  : 'No single setting fails every time, which points at BRAIN being busy rather than at the requests.'}
            </p>
            <table className="w-full text-body-compact">
              <thead className="text-ink-subtle">
                <tr>
                  <th className="py-1 text-left font-normal">Setting</th>
                  <th className="py-1 text-left font-normal">Value</th>
                  <th className="py-1 text-right font-normal">Failed / sent</th>
                </tr>
              </thead>
              <tbody>
                {data.slices.map((s) => (
                  <tr key={`${s.attribute}-${s.value}`} className="border-t border-hairline-subtle">
                    <td className="py-1 text-ink-muted">{s.attribute}</td>
                    <td className="max-w-0 truncate py-1 font-mono text-ink" title={s.value}>
                      {s.value}
                    </td>
                    <td
                      className={`num py-1 text-right ${s.failed === s.sent ? 'text-pnl-negative-text' : ''}`}
                    >
                      {fmt.int(s.failed)} / {fmt.int(s.sent)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data.examples.length > 0 && (
              <div className="flex flex-col gap-1">
                <span className="text-body-compact text-ink-subtle">Some that failed</span>
                {data.examples.map((e, i) => (
                  <div key={`${e.expression}-${i}`} className="flex flex-col">
                    <code className="font-mono text-body-compact break-all text-ink">
                      {e.expression}
                    </code>
                    <span className="text-body-compact text-ink-subtle">{e.settings}</span>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </Disclosure>
  )
}
