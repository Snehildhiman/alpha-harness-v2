/**
 * Current Theme Lab: simulates only Alphas that fit the running Power Pool theme, without an
 * LLM. The Search Lab held to the theme's rule: its delay, only datasets of the categories it
 * allows, one field per Alpha, no group operators or grouping fields when the theme forbids
 * them, inside the Power Pool limits.
 */

import { keepPreviousData, useMutation, useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { PlayIcon, TargetIcon } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { components } from '@/api/generated'
import { http } from '@/api/http'
import { fmt } from '@/lib/format'
import { useScopeOptions } from '@/lib/scope'
import { NeutralizationPicker } from '@/screens/research-labs/neutralization'
import {
  Badge,
  Button,
  Checkbox,
  Empty,
  ErrorNotice,
  Field,
  Input,
  LINK,
  Notice,
  Page,
  PageHeader,
  Panel,
  Segmented,
  Skeleton,
} from '@/ui/kit'

type Schemas = components['schemas']
type Options = Schemas['ThemeLabOptions']
type Preview = Schemas['ThemeLabPreview']

interface Body {
  region: string
  datasetIds: string[]
  neutralizations: string[]
  decay: number
  cores: number
  simulations: number
}

const wire = (b: Body) => ({
  region: b.region,
  dataset_ids: b.datasetIds,
  neutralizations: b.neutralizations,
  decay: b.decay,
  cores: b.cores,
  simulations: b.simulations,
})

const DECAYS = [0, 3, 5, 7, 10]

export function ThemeLabScreen() {
  const options = useQuery({
    queryKey: ['theme-lab', 'options'],
    queryFn: () => http.get<Options>('/api/theme-lab/options'),
  })
  const markets = options.data?.markets ?? []
  const [region, setRegion] = useState<string>('')
  const market = markets.find((m) => m.region === region) ?? markets[0]
  const [picked, setPicked] = useState<string[] | null>(null)
  const [neutralizations, setNeutralizations] = useState<string[]>([])
  const [decay, setDecay] = useState(0)
  const [cores, setCores] = useState(4)
  const [simulations, setSimulations] = useState(500)
  const delay = options.data?.delay ?? 1
  const scope = {
    instrumentType: 'EQUITY',
    region: market?.region ?? 'USA',
    delay,
    universe: '',
  }
  const scopeOptions = useScopeOptions(scope)
  useEffect(() => {
    if (!neutralizations.length && scopeOptions.neutralizations.length) {
      const first = scopeOptions.neutralizations.find((n) => n.value === 'SUBINDUSTRY')
      setNeutralizations([first?.value ?? scopeOptions.neutralizations[0]?.value ?? ''])
    }
  }, [scopeOptions.neutralizations, neutralizations.length])
  const all = (market?.datasets ?? []).map((d) => d.datasetId)
  const chosen = picked ?? all
  const body: Body = {
    region: market?.region ?? '',
    datasetIds: chosen,
    neutralizations,
    decay,
    cores,
    simulations,
  }
  const preview = useQuery({
    queryKey: ['theme-lab', 'preview', body],
    queryFn: () => http.post<Preview>('/api/theme-lab/preview', wire(body)),
    enabled: Boolean(market) && neutralizations.length > 0,
    placeholderData: keepPreviousData,
  })
  const add = useMutation({
    mutationFn: () => http.post<Schemas['AddedTask']>('/api/theme-lab/tasks', wire(body)),
  })
  const problems = preview.data?.problems ?? []

  return (
    <Page>
      <PageHeader
        title="Current Theme Lab"
        description="Simulates only Alphas that fit the running Power Pool theme, no LLM needed: the theme's delay, only datasets of its categories, one field per Alpha, no group operators or grouping fields, inside the Power Pool limits."
        actions={
          <Button
            variant="primary"
            loading={add.isPending}
            disabled={!market || problems.length > 0 || simulations < 1}
            onClick={() => add.mutate()}
          >
            <PlayIcon aria-hidden />
            Add and start
          </Button>
        }
      />
      {options.isError && <ErrorNotice error={options.error} title="Could not read the theme" />}
      {options.isPending && <Skeleton label="Reading the theme" />}
      {options.data && !options.data.theme && (
        <Notice tone="warn" title="No Power Pool theme is running today">
          Add the current one on{' '}
          <Link to="/types/$tab" params={{ tab: 'theme' }} className={LINK}>
            Alpha Types → Current Theme
          </Link>
          .
        </Notice>
      )}
      {options.data?.theme && (
        <Panel title={options.data.theme.name}>
          <div className="flex flex-col gap-4">
            <p className="num text-body-compact text-ink-muted">{options.data.rule}</p>
            {markets.length === 0 ? (
              <Empty icon={<TargetIcon />} title="No dataset of the theme is downloaded">
                Sync your markets at delay {delay} on{' '}
                <Link to="/sync" className={LINK}>
                  Sync with BRAIN
                </Link>
                .
              </Empty>
            ) : (
              <>
                <Segmented
                  label="Region"
                  items={markets.map((m) => ({ value: m.region, label: m.region }))}
                  value={market?.region ?? ''}
                  onChange={(r) => {
                    setRegion(r)
                    setPicked(null)
                  }}
                />
                <Field label={`Datasets (${fmt.int(chosen.length)} of ${fmt.int(all.length)})`}>
                  <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
                    {(market?.datasets ?? []).map((d) => (
                      <Checkbox
                        key={d.datasetId}
                        checked={chosen.includes(d.datasetId)}
                        onChange={(on) =>
                          setPicked(
                            on ? [...chosen, d.datasetId] : chosen.filter((x) => x !== d.datasetId),
                          )
                        }
                        label={
                          <span className="flex items-center gap-1.5">
                            <span className="font-mono text-body-compact">{d.datasetId}</span>
                            <span className="text-ink-subtle text-body-compact">
                              {d.category} · {fmt.int(d.alphas)} alphas
                            </span>
                            {d.themed && <Badge tone="profit">theme ×</Badge>}
                          </span>
                        }
                      />
                    ))}
                  </div>
                </Field>
                {scopeOptions.neutralizations.length === 0 && (
                  <p className="text-body-compact text-ink-subtle">
                    Neutralizations appear once you are signed in to BRAIN.
                  </p>
                )}
                <NeutralizationPicker
                  available={scopeOptions.neutralizations}
                  value={neutralizations}
                  onChange={setNeutralizations}
                />
                <div className="flex flex-wrap items-end gap-4">
                  <Field label="Decay">
                    <Segmented
                      label="Decay"
                      items={DECAYS.map((d) => ({ value: d, label: String(d) }))}
                      value={decay}
                      onChange={setDecay}
                    />
                  </Field>
                  <Field label="Cores">
                    <Segmented
                      label="Cores"
                      items={[1, 2, 4, 8].map((c) => ({ value: c, label: String(c) }))}
                      value={cores}
                      onChange={setCores}
                    />
                  </Field>
                  <Field label="Simulations">
                    <Input
                      type="number"
                      min={1}
                      className="w-32"
                      value={simulations}
                      onChange={(e) => setSimulations(Number(e.target.value))}
                    />
                  </Field>
                </div>
              </>
            )}
          </div>
        </Panel>
      )}
      {preview.isError && <ErrorNotice error={preview.error} title="Could not plan the task" />}
      {problems.map((p) => (
        <Notice key={p} tone="error" title={p} />
      ))}
      {preview.data?.warnings.map((w) => (
        <Notice key={w} tone="warn" title={w} />
      ))}
      {add.isError && <ErrorNotice error={add.error} title="Could not add the task" />}
      {add.isSuccess && (
        <Notice title={`Started task “${add.data.name}”`}>
          Watch it on{' '}
          <Link to="/tasks" className={LINK}>
            Tasks
          </Link>
          . Its passing Alphas land on Alpha Types → Current Theme.
        </Notice>
      )}
      {preview.data && preview.data.sample.length > 0 && (
        <Panel title="Example Alphas this task will send">
          <ul className="flex flex-col gap-1">
            {preview.data.sample.map((s) => (
              <li key={s.expression} className="font-mono text-body-compact">
                {s.expression}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-body-compact text-ink-subtle">
            {fmt.int(preview.data.fields?.total)} fields · universes{' '}
            {preview.data.universes.join(', ') || '—'}
          </p>
        </Panel>
      )}
    </Page>
  )
}
