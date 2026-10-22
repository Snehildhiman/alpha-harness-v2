/**
 * Models: what the app has learned from the vault, how well it holds up on Alphas it never
 * saw, and a box to ask it about an expression before spending a simulation on it.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BrainCircuitIcon, PlayIcon, SparklesIcon } from 'lucide-react'
import { useCallback, useState } from 'react'
import type { Scope } from '@/api/types'
import { fmt } from '@/lib/format'
import { useScopeOptions } from '@/lib/scope'
import { useRefetchOn } from '@/lib/ws'
import {
  Badge,
  Button,
  Empty,
  ErrorNotice,
  Field,
  Input,
  Metric,
  Notice,
  Page,
  PageHeader,
  Panel,
  Progress,
  Switch,
  Textarea,
  type Tone,
} from '@/ui/kit'
import { Select } from '@/ui/overlay'
import { ScopePicker } from '@/ui/scope-picker'
import { type Column, DataTable } from '@/ui/table'
import {
  type Candidate,
  modelStatus,
  type Prediction,
  predict,
  screening,
  type TargetReport,
  trainModels,
} from './api'
import { ModelHistory } from './history'

/** New or re-checked Alphas that earn an automatic retrain (backend `models.service.AUTO_NEW`). */
const AUTO_NEW = 100

type Quality = { tone: Tone; label: string }

/** Judged against a model that knows nothing, so an unhelpful model never reads as good. */
function quality(r: TargetReport): Quality {
  if (!r.trained) return { tone: 'muted', label: 'Not trained' }
  const m = r.metrics
  if (r.kind === 'classification') {
    const auc = m['auc'] ?? 0.5
    if (auc >= 0.75) return { tone: 'profit', label: 'Useful' }
    if (auc >= 0.62) return { tone: 'warn', label: 'Weak' }
    return { tone: 'loss', label: 'Not learning' }
  }
  const rank = m['spearman'] ?? 0
  const better = (m['mae'] ?? 1) < (m['baseline_mae'] ?? 1) * 0.85
  if (rank >= 0.5 && better) return { tone: 'profit', label: 'Useful' }
  if (rank >= 0.25) return { tone: 'warn', label: 'Weak' }
  return { tone: 'loss', label: 'Not learning' }
}

function score(r: TargetReport) {
  const m = r.metrics
  if (!r.trained) return r.note ?? '—'
  if (r.kind === 'classification') {
    return `AUC ${fmt.ratio(m['auc'])} · passes ${fmt.pct(m['base_rate'], 0)} of the time`
  }
  return `off by ${fmt.ratio(m['mae'], 3)} (guessing: ${fmt.ratio(m['baseline_mae'], 3)}) · rank match ${fmt.ratio(m['spearman'])}`
}

/** A feature column as a person would say it. */
function driver(name: string) {
  const [kind, rest] = name.includes(':')
    ? [name.split(':')[0], name.slice(name.indexOf(':') + 1)]
    : ['', name]
  switch (kind) {
    case 'op':
      return `uses ${rest}`
    case 'pair':
      return rest.replace('>', '(') + '(…))'
    case 'dataset':
      return `dataset ${rest}`
    case 'datacat':
      return `${rest} data`
  }
  const plain: Record<string, string> = {
    crowd_alpha_max: 'most crowded field',
    crowd_alpha_mean: 'field crowding',
    crowd_user_max: 'field users (max)',
    crowd_user_mean: 'field users',
    number_min: 'shortest lookback',
    number_max: 'longest lookback',
    number_median: 'typical lookback',
    nodes: 'expression size',
    depth: 'nesting depth',
    operator_count: 'operator count',
    field_count: 'field count',
    days: 'when simulated',
    power_pool: 'Power Pool',
  }
  return plain[name] ?? name.replaceAll('_', ' ')
}

const COLUMNS: Column<TargetReport>[] = [
  { key: 'label', header: 'Predicts', width: 'minmax(200px,1.4fr)', cell: (r) => r.label },
  {
    key: 'quality',
    header: 'On unseen Alphas',
    width: '130px',
    cell: (r) => {
      const q = quality(r)
      return <Badge tone={q.tone}>{q.label}</Badge>
    },
  },
  {
    key: 'score',
    header: 'Score',
    width: 'minmax(260px,2fr)',
    cell: (r) => <span className="text-body-compact">{score(r)}</span>,
  },
  {
    key: 'labelled',
    header: 'Labelled',
    width: '96px',
    align: 'right',
    cell: (r) => <span className="num">{fmt.int(r.labelled)}</span>,
  },
  {
    key: 'drivers',
    header: 'Driven most by',
    width: 'minmax(220px,2fr)',
    cell: (r) => (
      <span
        className="truncate text-body-compact text-ink-subtle"
        title={r.topFeatures.map(([n]) => driver(n)).join(', ')}
      >
        {r.topFeatures
          .slice(0, 3)
          .map(([n]) => driver(n))
          .join(', ') || '—'}
      </span>
    ),
  },
]

const BLANK: Candidate = {
  expression: '',
  region: 'USA',
  delay: 1,
  universe: 'TOP3000',
  neutralization: 'SUBINDUSTRY',
  decay: 4,
  truncation: 0.08,
  powerPool: false,
}

function PredictPanel({ ready, reports }: { ready: boolean; reports: TargetReport[] }) {
  const qualityOf = new Map(reports.map((r) => [r.target, quality(r)]))
  const [candidate, setCandidate] = useState<Candidate>(BLANK)
  const ask = useMutation({ mutationFn: predict })
  const set = (patch: Partial<Candidate>) => {
    // An answer for other inputs must not stay on screen as if it were for these.
    ask.reset()
    setCandidate((c) => ({ ...c, ...patch }))
  }
  const scope = {
    instrumentType: 'EQUITY',
    region: candidate.region,
    delay: candidate.delay,
    universe: candidate.universe,
  }
  const setScope = useCallback((change: Partial<Scope>) => {
    setCandidate((c) => ({ ...c, ...change }))
  }, [])
  const options = useScopeOptions(scope)
  const rows: Prediction[] = ask.data ?? []
  return (
    <Panel title="Ask before you simulate">
      <div className="flex flex-col gap-3">
        <Field label="Expression">
          <Textarea
            className="font-mono"
            value={candidate.expression}
            placeholder="rank(ts_delta(close, 5))"
            onChange={(e) => set({ expression: e.target.value })}
          />
        </Field>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-7">
          <div className="col-span-2 flex items-end lg:col-span-3">
            <ScopePicker scope={scope} onChange={setScope} />
          </div>
          <Field label="Neutralization">
            <Select
              label="Neutralization"
              mono
              items={
                options.neutralizations.length
                  ? options.neutralizations
                  : [{ value: candidate.neutralization, label: candidate.neutralization }]
              }
              value={candidate.neutralization}
              onChange={(value) => set({ neutralization: value })}
            />
          </Field>
          <Field label="Decay">
            <Input
              type="number"
              min={0}
              value={candidate.decay}
              onChange={(e) => set({ decay: Number(e.target.value) })}
            />
          </Field>
          <Field label="Truncation">
            <Input
              type="number"
              step={0.01}
              value={candidate.truncation}
              onChange={(e) => set({ truncation: Number(e.target.value) })}
            />
          </Field>
          <div className="flex h-8 items-center gap-2 self-end text-body-compact text-ink-muted">
            <Switch
              checked={candidate.powerPool ?? false}
              onChange={(on) => set({ powerPool: on })}
              aria-label="Power Pool"
            />
            Power Pool
          </div>
        </div>
        <div>
          <Button
            variant="primary"
            disabled={!ready || !candidate.expression.trim()}
            loading={ask.isPending}
            onClick={() => ask.mutate(candidate)}
          >
            <SparklesIcon aria-hidden />
            Predict
          </Button>
        </div>
        {ask.isError && <ErrorNotice error={ask.error} title="Could not predict" />}
        {rows.length > 0 && (
          <div className="grid grid-cols-1 gap-x-8 gap-y-1.5 sm:grid-cols-2 lg:grid-cols-3">
            {rows.map((p) => (
              <div
                key={p.target}
                className="flex items-baseline justify-between gap-3 border-b border-hairline-subtle py-1"
              >
                <span className="text-body-compact text-ink-muted">
                  {p.label}
                  {qualityOf.get(p.target)?.label === 'Not learning' && (
                    <span
                      className="ml-1.5 text-ink-subtle"
                      title="This model does no better than guessing on unseen Alphas; ignore this number"
                    >
                      (guess)
                    </span>
                  )}
                </span>
                <span
                  className={`num ${
                    qualityOf.get(p.target)?.label === 'Not learning'
                      ? 'text-ink-subtle line-through'
                      : ''
                  } ${
                    p.kind === 'probability'
                      ? p.value >= 0.6
                        ? 'text-pnl-positive-text'
                        : p.value < 0.4
                          ? 'text-pnl-negative-text'
                          : ''
                      : ''
                  }`}
                >
                  {p.kind === 'probability' ? fmt.pct(p.value, 0) : fmt.ratio(p.value, 3)}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </Panel>
  )
}

/** Whether the screen earns its keep: model picks against random picks from the same rounds. */
function ScreeningPanel() {
  const report = useQuery(screening)
  const groups = report.data?.groups ?? []
  if (groups.length === 0) return null
  const share = (g: (typeof groups)[number]) => {
    const judged = g.passing + g.refused
    return judged ? g.passing / judged : null
  }
  const label: Record<string, string> = {
    model: 'Picked by the models',
    explore: 'Picked at random (exploration)',
  }
  return (
    <Panel title="Screening in the labs">
      <div className="flex flex-col gap-3">
        <p className="text-body text-ink-subtle">
          Of the screened Alphas BRAIN has judged, the share that passed every check their type
          answers to. If the models help, their picks pass more often than the random ones.
        </p>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {groups.map((g) => (
            <Metric
              key={g.group}
              boxed
              label={label[g.group] ?? g.group}
              value={fmt.pct(share(g))}
              hint={`${fmt.int(g.passing)} passed, ${fmt.int(g.refused)} failed, ${fmt.int(g.pending)} waiting on checks${g.predicted === null || g.predicted === undefined ? '' : ` · models expected ${fmt.pct(g.predicted)}`}`}
            />
          ))}
        </div>
      </div>
    </Panel>
  )
}

export function ModelsScreen() {
  const client = useQueryClient()
  const status = useQuery({
    ...modelStatus,
    refetchInterval: (q) => (q.state.data?.training ? 2000 : false),
  })
  useRefetchOn('tasks', ['models'], 2000)
  const train = useMutation({
    mutationFn: trainModels,
    onSuccess: () => void client.invalidateQueries({ queryKey: ['models'] }),
  })
  const data = status.data
  const reports = data?.reports ?? []
  const main = reports.filter((r) => !r.target.startsWith('check:'))
  const checks = reports.filter((r) => r.target.startsWith('check:'))
  const training = data?.training

  return (
    <Page>
      <PageHeader
        title="Models"
        description="Learned from every Alpha in your vault. Each is tested on your newest Alphas, which it never saw, beside what blind guessing would score."
        actions={
          <Button
            variant="primary"
            loading={train.isPending || !!training}
            onClick={() => train.mutate()}
          >
            <PlayIcon aria-hidden />
            {data?.trainedAt ? 'Retrain' : 'Train models'}
          </Button>
        }
      />
      {train.isError && <ErrorNotice error={train.error} title="Could not start training" />}
      {status.isError && <ErrorNotice error={status.error} title="Could not read the models" />}
      {training && (
        <Panel>
          <div className="flex flex-col gap-2">
            <span className="text-body-compact text-ink-muted">
              Training {training[0]} of {training[1]}: {training[2].replace('check:', 'check ')}
            </span>
            <Progress value={training[0] / Math.max(1, training[1])} />
          </div>
        </Panel>
      )}
      {!data?.trainedAt ? (
        <Panel>
          <Empty icon={<BrainCircuitIcon />} title="No models yet">
            Sync your Alphas and the data catalog first, then press Train models. About a minute for
            50,000 Alphas.
          </Empty>
        </Panel>
      ) : (
        <>
          <Notice title={`Trained ${fmt.ago(data.trainedAt)} on ${fmt.int(data.alphas)} Alphas`}>
            Scores are on Alphas simulated from {fmt.date(data.testFrom)} onward, held out of
            training. “Useful” means it ranks those Alphas clearly better than guessing; retrain as
            new results arrive.
          </Notice>
          <Notice
            title={
              data.auto
                ? `Learning by itself: ${fmt.int(data.newSinceTraining)} new or re-checked Alphas since training`
                : 'Automatic retraining is off'
            }
          >
            {data.auto
              ? `It retrains once ${fmt.int(AUTO_NEW)} have arrived, and only keeps the new models if they do at least as well on Alphas the current ones never saw.`
              : 'Turn it back on in Settings, or press Retrain.'}
            {data.lastGate && (
              <span className="mt-1 block">
                Last automatic retrain {fmt.ago(data.lastGate.at)}:{' '}
                <span
                  className={
                    data.lastGate.accepted ? 'text-pnl-positive-text' : 'text-status-warning'
                  }
                >
                  {data.lastGate.accepted ? 'replaced the models' : 'kept the old models'}
                </span>
                . {data.lastGate.reason}
              </span>
            )}
          </Notice>
          <Panel title="Figures and correlations">
            <DataTable
              rows={main}
              columns={COLUMNS}
              rowKey={(r) => r.target}
              label="Model accuracy"
              maxHeight="none"
            />
          </Panel>
          <Panel title="Pass or fail, check by check">
            <DataTable
              rows={checks}
              columns={COLUMNS}
              rowKey={(r) => r.target}
              label="Check models"
              maxHeight="none"
            />
          </Panel>
        </>
      )}
      <ModelHistory />
      <ScreeningPanel />
      <PredictPanel ready={!!data?.trainedAt} reports={data?.reports ?? []} />
    </Page>
  )
}
