/**
 * Current Theme Lab: simulates only Alphas that fit the running Power Pool theme, without an
 * LLM. The Search Lab held to the theme's rule: its delay, only datasets of the categories it
 * allows, one field per Alpha, no PV1 group fields (industry, sector...) when the theme forbids
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
import { UniverseSetting } from '@/screens/research-labs/task-settings'
import {
  Badge,
  Button,
  Checkbox,
  Chips,
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
  Switch,
} from '@/ui/kit'
import { ThemeComboPanel } from './combo'
import { ThemeTemplatePicker } from './templates'

type Schemas = components['schemas']
type Options = Schemas['ThemeLabOptions']
type Preview = Schemas['ThemeLabPreview']

type Mode = 'FULL' | 'QUICK' | 'AUTO'

interface Body {
  theme: string | null
  templates: string[]
  searchShapes: boolean
  withinCountry: boolean
  simulationMode: Mode
  vectorOperators: string[]
  region: string
  datasetIds: string[]
  neutralizations: string[]
  decay: number
  cores: number
  simulations: number
  universes: string[]
  randomUniverse: boolean
}

const wire = (b: Body) => ({
  theme: b.theme,
  templates: b.templates,
  search_shapes: b.searchShapes,
  within_country: b.withinCountry,
  simulation_mode: b.simulationMode,
  universes: b.universes,
  random_universe: b.randomUniverse,
  vector_operators: b.vectorOperators,
  region: b.region,
  dataset_ids: b.datasetIds,
  neutralizations: b.neutralizations,
  decay: b.decay,
  cores: b.cores,
  simulations: b.simulations,
})

const DECAYS = [0, 3, 5, 7, 10]

export function ThemeLabScreen() {
  // null: the latest-starting theme running today or opening within the week.
  const [themeName, setThemeName] = useState<string | null>(null)
  const options = useQuery({
    queryKey: ['theme-lab', 'options', themeName],
    queryFn: () =>
      http.get<Options>(
        `/api/theme-lab/options${themeName ? `?theme=${encodeURIComponent(themeName)}` : ''}`,
      ),
    placeholderData: keepPreviousData,
  })
  const themes = options.data?.themes ?? []
  const theme = options.data?.theme ?? null
  const markets = options.data?.markets ?? []
  const [region, setRegion] = useState<string>('')
  const market = markets.find((m) => m.region === region) ?? markets[0]
  const [picked, setPicked] = useState<string[] | null>(null)
  const [neutralizations, setNeutralizations] = useState<string[]>([])
  const [decay, setDecay] = useState(0)
  const [cores, setCores] = useState(4)
  const [simulations, setSimulations] = useState(500)
  const [universes, setUniverses] = useState<string[]>([])
  const [templates, setTemplates] = useState<string[]>([])
  const [searchShapes, setSearchShapes] = useState(true)
  const [withinCountry, setWithinCountry] = useState(true)
  // Templates chosen: simulate those, not the lab's own shapes, unless asked for both.
  const chooseTemplates = (names: string[]) => {
    if (!templates.length && names.length) setSearchShapes(false)
    if (!names.length) setSearchShapes(true)
    setTemplates(names)
  }
  const [mode, setMode] = useState<Mode>('FULL')
  const [randomUniverse, setRandomUniverse] = useState(false)
  // Vector fields (several values a day) need a vec_ operator to become one number; most
  // analyst and model data is vector, so vec_avg is on from the start.
  const lab = useQuery({
    queryKey: ['search-lab', 'options'],
    queryFn: () => http.get<Schemas['Options']>('/api/search-lab/options'),
  })
  const vectorAvailable = lab.data?.vector ?? []
  const [vectorPicked, setVectorPicked] = useState<string[] | null>(null)
  const vectorOperators =
    vectorPicked ??
    (vectorAvailable.includes('vec_avg') ? ['vec_avg'] : vectorAvailable.slice(0, 1))
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
  const recommended = (market?.datasets ?? [])
    .filter((d) => d.recommended || d.lessCrowded)
    .map((d) => d.datasetId)
  const chosen = picked ?? (recommended.length ? recommended : all)
  const body: Body = {
    theme: theme?.name ?? null,
    templates,
    searchShapes,
    withinCountry,
    simulationMode: mode,
    vectorOperators,
    region: market?.region ?? '',
    datasetIds: chosen,
    neutralizations,
    decay,
    cores,
    simulations,
    universes,
    randomUniverse,
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
        description="Simulates only Alphas that fit a Power Pool theme running now or opening this week, no LLM needed: the theme's delay and region, its datasets (the recommended ones first), one field per Alpha, no PV1 group fields where the theme forbids them, inside the Power Pool limits."
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
            {themes.length > 1 && (
              <Segmented
                label="Theme"
                items={themes.map((t) => ({
                  value: t.name,
                  label: `${t.name} (${t.start} – ${t.end})`,
                }))}
                value={theme?.name ?? ''}
                onChange={(name) => {
                  setThemeName(name)
                  setRegion('')
                  setPicked(null)
                }}
              />
            )}
            <p className="num text-body-compact text-ink-muted">
              {options.data.rule}
              {options.data.theme.multiplier ? ` · ${options.data.theme.multiplier}x` : ''} · runs{' '}
              {options.data.theme.start} to {options.data.theme.end}
            </p>
            {Object.keys(options.data.theme.subRegionSharpe ?? {}).length > 0 && (
              <p className="text-body-compact text-pretty text-ink-subtle">
                Judged on your theme Alphas combined (BC and AC Combo IR, OS Score). Each Alpha is
                scored on its train-years Sharpe before and after a 5 bps trading cost, so the
                held-out years show whether it holds up, and loses score when its{' '}
                {Object.entries(options.data.theme.subRegionSharpe ?? {})
                  .map(([area, floor]) => `${area} Sharpe is ${floor} or less`)
                  .join(', ')}
                . On GLB every Alpha is also ranked or z-scored within its country, so no market’s
                larger raw values carry the book, fields under 70% coverage are left out, and an
                Alpha loses score when AMER, APAC or EMEA is 1 or less or when one sub-region
                carries it. A higher decay lowers turnover, which lifts the after-cost figures.
                Below, “What to submit next” picks the Alphas that lift the combination most.
              </p>
            )}
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
                  {recommended.length > 0 && (
                    <div className="mb-2 flex flex-wrap gap-2">
                      <Button size="sm" variant="secondary" onClick={() => setPicked(recommended)}>
                        Recommended only ({fmt.int(recommended.length)})
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setPicked(all)}>
                        All
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setPicked([])}>
                        Clear
                      </Button>
                    </div>
                  )}
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
                            {d.recommended && <Badge>recommended</Badge>}
                            {d.lessCrowded && <Badge tone="profit">less crowded</Badge>}
                          </span>
                        }
                      />
                    ))}
                  </div>
                </Field>
                <ThemeTemplatePicker
                  theme={theme?.name ?? null}
                  value={templates}
                  onChange={chooseTemplates}
                  shapes={searchShapes}
                  onShapes={setSearchShapes}
                />
                {market?.region === 'GLB' && (
                  <div className="flex items-start gap-2 text-body-compact text-ink-muted">
                    <Switch
                      checked={withinCountry}
                      onChange={setWithinCountry}
                      aria-label="Rank each Alpha within its country"
                    />
                    <span className="text-pretty">
                      Rank or z-score each Alpha within its country (BRAIN’s GLB advice, so one
                      market’s larger values do not carry the book). Off: every template is sent
                      exactly as written.
                    </span>
                  </div>
                )}
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
                {vectorAvailable.length > 0 && (
                  <Field
                    label="Vector operators"
                    hint="Turn a vector field (several values a day) into one number. Most analyst and model data is vector, so leave at least one on."
                  >
                    <Chips
                      label="Vector operators"
                      items={vectorAvailable.map((op) => ({ value: op, label: op }))}
                      value={vectorOperators}
                      onChange={setVectorPicked}
                    />
                  </Field>
                )}
                <UniverseSetting
                  offered={preview.data?.offeredUniverses ?? []}
                  value={universes}
                  random={randomUniverse}
                  onChange={(change) => {
                    if (change.universes) setUniverses(change.universes)
                    if (change.randomUniverse !== undefined)
                      setRandomUniverse(change.randomUniverse)
                  }}
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
                  <Field
                    label="Check"
                    hint="Full: a normal simulation with every check BRAIN runs. Quick: fewer checks and faster; a passing Alpha is re-run in Full before it counts."
                  >
                    <Segmented
                      label="Check"
                      items={[
                        { value: 'FULL' as Mode, label: 'Full' },
                        { value: 'QUICK' as Mode, label: 'Quick' },
                        { value: 'AUTO' as Mode, label: 'As in Settings' },
                      ]}
                      value={mode}
                      onChange={setMode}
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
      {theme && <ThemeComboPanel theme={theme.name} />}
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
