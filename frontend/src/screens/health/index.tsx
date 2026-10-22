/**
 * Health: everything that keeps the app finding alphas on one screen, each ok, worth a look,
 * or broken, with the screen that fixes it. Backups are made and downloaded here too.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ArchiveIcon, DownloadIcon, HeartPulseIcon } from 'lucide-react'
import type { components } from '@/api/generated'
import { http } from '@/api/http'
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
  Skeleton,
} from '@/ui/kit'

type Schemas = components['schemas']

const LEVEL = {
  ok: { tone: 'profit', label: 'OK' },
  warn: { tone: 'warn', label: 'Look' },
  bad: { tone: 'loss', label: 'Fix' },
} as const

const size = (bytes: number) =>
  bytes > 1e9 ? `${(bytes / 1e9).toFixed(1)} GB` : `${(bytes / 1e6).toFixed(0)} MB`

export function HealthScreen() {
  const client = useQueryClient()
  const health = useQuery({
    queryKey: ['overview', 'health'],
    queryFn: () => http.get<Schemas['AppHealth']>('/api/overview/health'),
    refetchInterval: 30_000,
  })
  const backups = useQuery({
    queryKey: ['overview', 'backups'],
    queryFn: () => http.get<Schemas['Backup'][]>('/api/overview/backups'),
  })
  const backup = useMutation({
    mutationFn: () => http.post<Schemas['Backup']>('/api/overview/backups'),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['overview'] })
    },
  })

  return (
    <Page>
      <PageHeader
        title="Health"
        description="Session, catalog, models, tasks, simulations, keys and disk at a glance. Each line links to the screen that fixes it."
      />
      <Panel title="Status">
        {health.isPending && <Skeleton className="h-64 w-full" label="Reading the app's health" />}
        {health.isError && <ErrorNotice error={health.error} title="Could not read the health" />}
        {health.data && (
          <ul className="flex flex-col divide-y divide-hairline">
            {health.data.items.map((item) => {
              const level = LEVEL[item.level as keyof typeof LEVEL] ?? LEVEL.ok
              return (
                <li key={item.key} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2.5">
                  <Badge tone={level.tone} className="w-12 justify-center">
                    {level.label}
                  </Badge>
                  <span className="w-48 text-body text-ink">{item.label}</span>
                  <span className="num flex-1 text-body-compact text-ink-muted">
                    {item.value}
                    {item.detail && <span className="text-ink-subtle"> · {item.detail}</span>}
                  </span>
                  {item.link && item.level !== 'ok' && (
                    <Link to={item.link} className={LINK}>
                      Open
                    </Link>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </Panel>
      <Panel
        title="Backups"
        description="Your alphas and their daily PnL, the crowd history, the models and the app's database, in one zip in your data folder. Saved passwords and API keys stay locked: the key to them is not in the zip. The newest 10 are kept."
        actions={
          <Button variant="primary" loading={backup.isPending} onClick={() => backup.mutate()}>
            <ArchiveIcon aria-hidden />
            Back up now
          </Button>
        }
      >
        {backup.isError && <ErrorNotice error={backup.error} title="Could not make the backup" />}
        {backup.isSuccess && (
          <Notice title={`Saved ${backup.data.name} (${size(backup.data.bytes)})`} />
        )}
        {backups.data && backups.data.length === 0 ? (
          <Empty icon={<HeartPulseIcon />} title="No backup yet">
            One click above. A backup takes under a minute.
          </Empty>
        ) : (
          <ul className="flex flex-col divide-y divide-hairline">
            {(backups.data ?? []).map((b) => (
              <li key={b.name} className="flex items-center gap-4 py-2">
                <span className="num flex-1 text-body-compact">{b.name}</span>
                <span className="num text-body-compact text-ink-subtle">
                  {fmt.dateTime(b.createdAt)}
                </span>
                <span className="num w-20 text-right text-body-compact text-ink-subtle">
                  {size(b.bytes)}
                </span>
                <a
                  className={LINK}
                  href={`/api/overview/backups/${encodeURIComponent(b.name)}`}
                  download
                >
                  <DownloadIcon aria-hidden className="inline size-4" /> Download
                </a>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </Page>
  )
}
