/**
 * Check before submitting: BRAIN's submission checks run again for one alpha, right now, so a
 * correlation that rose since the last check is caught before you submit it on BRAIN.
 * Spends no simulations.
 */

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ShieldCheckIcon } from 'lucide-react'
import type { components } from '@/api/generated'
import { errorMessage, http } from '@/api/http'
import { Button, LINK } from '@/ui/kit'

type Presubmit = components['schemas']['Presubmit']

const short = (name: string) => name.replaceAll('_', ' ').toLowerCase()

export function PresubmitButton({ alphaId }: { alphaId: string }) {
  const client = useQueryClient()
  const check = useMutation({
    mutationFn: () => http.post<Presubmit>('/api/overview/presubmit', { alphaId }),
    meta: { inline: true },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['separation'] })
    },
  })
  const result = check.data
  return (
    <span className="flex min-w-0 items-center gap-2">
      {!result && (
        <Button
          size="sm"
          loading={check.isPending}
          onClick={(e) => {
            e.stopPropagation()
            check.mutate()
          }}
          title="Run BRAIN's checks again now, before you submit (no simulations spent)"
        >
          <ShieldCheckIcon aria-hidden />
          Check now
        </Button>
      )}
      {check.isError && (
        <span
          className="truncate text-body-compact text-pnl-negative-text"
          title={errorMessage(check.error)}
        >
          {errorMessage(check.error)}
        </span>
      )}
      {result?.ok && (
        <a
          href={result.link}
          target="_blank"
          rel="noreferrer"
          className={LINK}
          title={`Checked ${result.checkedAt}`}
        >
          Passes now · submit on BRAIN
        </a>
      )}
      {result && !result.ok && (
        <button
          type="button"
          className="truncate text-body-compact text-pnl-negative-text"
          title="Check again"
          onClick={(e) => {
            e.stopPropagation()
            check.mutate()
          }}
        >
          {result.verdict === 'pending'
            ? 'BRAIN still computing · check again'
            : `Fails: ${result.failed
                .map(
                  (f) => `${short(f.name)} ${f.value ?? ''}${f.limit != null ? `/${f.limit}` : ''}`,
                )
                .join(', ')}`}
        </button>
      )}
    </span>
  )
}
