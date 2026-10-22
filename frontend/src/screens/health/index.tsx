/**
 * Health: everything that keeps the app finding alphas on one screen, each ok, worth a look,
 * or broken, with the screen that fixes it. Backups are made and downloaded here too.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ArchiveIcon, DownloadIcon, HeartPulseIcon, RotateCcwIcon, UploadIcon } from 'lucide-react'
import { useRef, useState } from 'react'
import type { components } from '@/api/generated'
import { ApiError, errorMessage, http, normalise } from '@/api/http'
import { fmt } from '@/lib/format'
import { usePreferences, useSavePreferences } from '@/lib/preferences'
import {
  Badge,
  Button,
  Checkbox,
  Disclosure,
  Empty,
  ErrorNotice,
  LINK,
  Notice,
  Page,
  PageHeader,
  Panel,
  Segmented,
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
          <div className="flex flex-wrap items-center gap-2">
            <AutoBackup />
            <UploadBackup />
            <Button variant="primary" loading={backup.isPending} onClick={() => backup.mutate()}>
              <ArchiveIcon aria-hidden />
              Back up now
            </Button>
          </div>
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
                <RestoreBackup name={b.name} />
              </li>
            ))}
          </ul>
        )}
      </Panel>
      <BrainErrors />
    </Page>
  )
}

/** How often a backup is made by itself. */
function AutoBackup() {
  const prefs = usePreferences()
  const save = useSavePreferences()
  if (!prefs.data) return null
  return (
    <Segmented
      label="Automatic backup"
      items={[
        { value: 0 as const, label: 'Off' },
        { value: 1 as const, label: 'Daily' },
        { value: 7 as const, label: 'Weekly' },
      ]}
      value={prefs.data.autoBackupDays}
      onChange={(autoBackupDays) => prefs.data && save.mutate({ ...prefs.data, autoBackupDays })}
    />
  )
}

/** A backup from another computer, to restore here. */
function UploadBackup() {
  const client = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const upload = useMutation({
    mutationFn: async (file: File) => {
      const response = await fetch('/api/overview/backups/upload', {
        method: 'POST',
        headers: { 'X-Harness-Client': '1', 'Content-Type': 'application/zip' },
        body: file,
      })
      const raw: unknown = await response.json().catch(() => null)
      if (!response.ok) throw new ApiError(response.status, normalise(response.status, raw))
      return raw
    },
    onSuccess: () => void client.invalidateQueries({ queryKey: ['overview', 'backups'] }),
  })
  return (
    <>
      <input
        ref={input}
        type="file"
        accept=".zip,application/zip"
        className="hidden"
        aria-label="Backup file"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) upload.mutate(file)
          e.target.value = ''
        }}
      />
      <Button loading={upload.isPending} onClick={() => input.current?.click()}>
        <UploadIcon aria-hidden />
        Add a backup file
      </Button>
    </>
  )
}

/** Put a backup's alphas, PnL and crowd history back: only what is missing is added. */
function RestoreBackup({ name }: { name: string }) {
  const client = useQueryClient()
  const [models, setModels] = useState(false)
  const [database, setDatabase] = useState(false)
  const restore = useMutation({
    mutationFn: () =>
      http.post<components['schemas']['Restored']>(
        `/api/overview/backups/${encodeURIComponent(name)}/restore`,
        { models, database },
      ),
    meta: { inline: true },
    onSuccess: () => void client.invalidateQueries(),
  })
  const added = restore.data ? Object.values(restore.data.added).reduce((a, b) => a + b, 0) : null
  return (
    <Disclosure summary="Restore">
      <div className="flex flex-col gap-2 py-2">
        <p className="text-body-compact text-ink-subtle">
          Adds back every alpha, PnL day and crowd snapshot in this backup that is missing here.
          Nothing newer is replaced or deleted.
        </p>
        <Checkbox
          label="Also its models (replaces the models in use)"
          checked={models}
          onChange={setModels}
        />
        <Checkbox
          label="Also its tasks, settings and prompts (at the next start; the current ones are kept aside)"
          checked={database}
          onChange={setDatabase}
        />
        <div>
          <Button loading={restore.isPending} onClick={() => restore.mutate()}>
            <RotateCcwIcon aria-hidden />
            Restore
          </Button>
        </div>
        {restore.isError && (
          <span className="text-body-compact text-pnl-negative-text">
            {errorMessage(restore.error)}
          </span>
        )}
        {restore.data && (
          <span className="text-body-compact text-ink-muted">
            Added {fmt.int(added)} rows
            {restore.data.models ? ', restored the models' : ''}
            {restore.data.database ? '; tasks and settings come back when you restart the app' : ''}
            .
          </span>
        )}
      </div>
    </Disclosure>
  )
}

/** Why BRAIN refused simulations lately, grouped, with what to do about each. */
function BrainErrors() {
  const [days, setDays] = useState(7)
  const errors = useQuery({
    queryKey: ['overview', 'errors', days],
    queryFn: () =>
      http.get<components['schemas']['ErrorSummary']>(`/api/overview/errors?days=${days}`),
  })
  const data = errors.data
  return (
    <Panel
      title="Why BRAIN refused simulations"
      description="Grouped by BRAIN's own message, most common first. A refusal marked Fix repeats until its cause is fixed; the app no longer re-sends those, but the lab keeps writing them until the field, operator or template is changed."
      actions={
        <Segmented
          label="Period"
          items={[
            { value: 1, label: '1 day' },
            { value: 7, label: '7 days' },
            { value: 30, label: '30 days' },
          ]}
          value={days}
          onChange={setDays}
        />
      }
    >
      {errors.isPending && <Skeleton className="h-24 w-full" label="Reading refusals" />}
      {errors.isError && <ErrorNotice error={errors.error} title="Could not read the refusals" />}
      {data && data.groups.length === 0 && (
        <Empty title="No refusals">BRAIN refused nothing in this period.</Empty>
      )}
      {data && data.groups.length > 0 && (
        <ul className="flex flex-col divide-y divide-hairline">
          {data.groups.map((g) => (
            <li key={g.reason} className="flex flex-col gap-1 py-2.5">
              <div className="flex flex-wrap items-center gap-3">
                <span className="num w-14 text-right text-body text-ink">{fmt.int(g.count)}</span>
                <Badge tone={g.forGood ? 'loss' : 'outline'}>{g.forGood ? 'Fix' : 'Passes'}</Badge>
                <span
                  className="min-w-0 flex-1 truncate text-body-compact text-ink"
                  title={g.example}
                >
                  {g.example}
                </span>
                <span className="text-caption text-ink-subtle">{fmt.ago(g.lastAt)}</span>
              </div>
              {g.advice && (
                <span className="pl-17 text-body-compact text-ink-muted">{g.advice}</span>
              )}
              {g.expression && (
                <span
                  className="truncate pl-17 font-mono text-body-compact text-ink-subtle"
                  title={g.expression}
                >
                  e.g. {g.expression}
                </span>
              )}
              {g.tasks.length > 0 && (
                <span className="pl-17 text-caption text-ink-subtle">
                  Tasks: {g.tasks.join(', ')}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}
