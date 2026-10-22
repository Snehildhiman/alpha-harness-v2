/**
 * Region Agnostic Lab: the built-in shapes (no LLM) or an LLM write Alphas from region-agnostic fields, and each runs as an
 * ordinary simulation in every chosen region that carries its fields, the settings the same
 * but for the region. BRAIN runs two region-agnostic simulations at a time; this runs none.
 */

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useEffect } from 'react'
import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { fmt } from '@/lib/format'
import { useCores } from '@/lib/preferences'
import { REGION_AGNOSTIC, useScopeOptions } from '@/lib/scope'
import { useProviderLabel } from '@/screens/ai/shared'
import type { PickedField } from '@/screens/data/dataset-pick'
import type { FieldFilterState } from '@/screens/data/state'
import { PromptPicker, useChosenPrompt } from '@/screens/prompts/picker'
import { ResearchPicked, useResearchIds } from '@/screens/research/picked'
import { AddTaskButtons, useAddTask } from '@/screens/research-labs/add-task'
import {
  fieldIdsOf,
  MAX_SIMULATIONS,
  simulationsValid,
  useLabMarket,
  useLabPreview,
} from '@/screens/research-labs/lab-task'
import { NeutralizationPicker } from '@/screens/research-labs/neutralization'
import {
  type RegionAgnosticRequest,
  regionAgnosticLab,
} from '@/screens/research-labs/region-agnostic/api'
import {
  CoresSetting,
  DatasetsPanel,
  SimulationsSetting,
} from '@/screens/research-labs/task-settings'
import {
  Button,
  Chips,
  Disclosure,
  ErrorNotice,
  Fieldset,
  LINK,
  Metric,
  Notice,
  Page,
  PageHeader,
  Panel,
  Segmented,
} from '@/ui/kit'
import { Select } from '@/ui/overlay'

const SIZES = ['LARGE', 'MEDIUM', 'SMALL', 'RANDOM'] as const
type Size = (typeof SIZES)[number]

/** The built-in this lab sends, and the kind of every saved prompt it can send instead. */
const PROMPT_KIND = 'region_agnostic_lab'

interface RegionAgnosticDraft {
  /** Always the All Regions market: that is where region-agnostic fields are chosen. */
  region: string
  delay: number
  universe: string
  datasetIds: string[]
  /** Unused here: fields are chosen by id, but every lab's market has one. */
  fieldFilter: FieldFilterState | null
  fields?: PickedField[]
  rankBy?: string | null
  regions: string[]
  /** BRAIN's region-agnostic universe size; each region's universe follows from it. */
  size?: Size
  /** `null` until chosen in the form: until then Settings' default applies. */
  cores: number | null
  simulations: number | null
  model: string | null
  promptId: number | null
  neutralizations: string[]
  /** Who writes the Alphas: the built-in shapes need no LLM. */
  writer?: 'llm' | 'shapes'
  /** When an expression earns a real region-agnostic simulation. */
  promote?: 'near' | 'strict' | 'off'
}

const useDraft = create<RegionAgnosticDraft>()(
  persist(
    (): RegionAgnosticDraft => ({
      region: REGION_AGNOSTIC,
      delay: 1,
      universe: '',
      datasetIds: [],
      fieldFilter: null,
      fields: [],
      rankBy: null,
      regions: ['USA', 'EUR', 'ASI', 'GLB'],
      size: 'LARGE',
      cores: null,
      simulations: null,
      model: null,
      promptId: null,
      neutralizations: [],
      writer: 'shapes',
    }),
    { name: 'alpha-harness-region-agnostic-lab' },
  ),
)

const PRE =
  'num max-h-80 overflow-auto rounded-md border border-hairline bg-canvas p-3 text-body-compact whitespace-pre-wrap text-ink-muted'

export function RegionAgnosticLabScreen() {
  const draft = useDraft()
  const set = useDraft.setState
  const { panel } = useLabMarket(draft, set, '/labs/region-agnostic')
  const options = useQuery({
    queryKey: ['region-agnostic-lab', 'options', draft.delay],
    queryFn: () => regionAgnosticLab.options(draft.delay),
  })
  const allRegions = useScopeOptions({
    instrumentType: 'EQUITY',
    region: REGION_AGNOSTIC,
    delay: draft.delay,
    universe: draft.universe,
  })
  // The All Regions market's universe the fields are picked in: the first BRAIN offers.
  const firstUniverse = allRegions.universes[0]?.value
  useEffect(() => {
    if (!draft.universe && firstUniverse) set({ universe: firstUniverse })
  }, [draft.universe, firstUniverse])

  const models = options.data?.models ?? []
  const providerLabel = useProviderLabel()
  const cores = useCores(draft.cores)
  const model =
    draft.model && models.some((m) => m.ref === draft.model)
      ? draft.model
      : (options.data?.defaultModel ?? null)
  const promptId = useChosenPrompt(PROMPT_KIND, draft.promptId ?? null)
  const offered = options.data?.regions ?? []
  const regions = draft.regions.filter((r) => offered.some((o) => o.region === r))
  // BRAIN's region-agnostic universe setting: one size, a universe per region.
  const size = draft.size ?? 'LARGE'
  const universeOf = (region: string) =>
    size === 'RANDOM'
      ? ['LARGE', 'MEDIUM', 'SMALL']
          .map((s) => options.data?.sizes[s]?.[region])
          .filter(Boolean)
          .join(' / ')
      : (options.data?.sizes[size]?.[region] ?? '')
  const shared = offered
    .filter((o) => regions.includes(o.region))
    .map((o) => o.neutralizations)
    .reduce<string[] | null>(
      (acc, list) => (acc ? acc.filter((n) => list.includes(n)) : list),
      null,
    )

  const writer = draft.writer ?? 'shapes'
  const shapes = writer === 'shapes'
  const researchIds = useResearchIds()
  const body: RegionAgnosticRequest = {
    delay: draft.delay,
    universe: draft.universe,
    regions,
    size,
    field_ids: fieldIdsOf(draft),
    dataset_ids: draft.datasetIds,
    rank_by: draft.fields?.length ? (draft.rankBy ?? null) : null,
    model,
    prompt_id: promptId,
    neutralizations: draft.neutralizations,
    cores,
    simulations: draft.simulations ?? 0,
    research_ids: shapes ? [] : researchIds,
    writer,
    promote: draft.promote ?? 'near',
  }
  const { preview, current } = useLabPreview('region-agnostic-lab', body, regionAgnosticLab.preview)
  const plan = preview.data
  const maxSimulations = options.data?.maxSimulations ?? MAX_SIMULATIONS
  const add = useAddTask(() => regionAgnosticLab.addTask(body))
  const ready =
    plan !== undefined &&
    current &&
    plan.problems.length === 0 &&
    simulationsValid(draft.simulations, maxSimulations)

  return (
    <Page>
      <PageHeader
        title="Region Agnostic Lab"
        description="Region-agnostic fields, written into Alphas by the built-in shapes (no LLM) or by an LLM, and run as ordinary simulations in every region that carries them: the same settings but the region, ten to a core. Results come back grouped by Alpha, a row per region."
        actions={<AddTaskButtons add={add} disabled={!ready} />}
      />
      <ArcPanel
        chosen={draft.datasetIds}
        promote={draft.promote ?? 'near'}
        delay={draft.delay}
        onDatasets={(ids) => set({ datasetIds: ids, fields: [], fieldFilter: null })}
        onPromote={(promote) => set({ promote })}
        onDelay={() => set({ delay: 1, universe: '' })}
      />
      <Panel title="Writer">
        <div className="flex flex-col gap-3">
          <Segmented
            label="Writer"
            items={[
              { value: 'shapes' as const, label: 'Built-in shapes · no LLM' },
              { value: 'llm' as const, label: 'LLM' },
            ]}
            value={writer}
            onChange={(next) => set({ writer: next })}
          />
          <p className="text-body-compact text-pretty text-ink-subtle">
            {shapes
              ? 'Nineteen shapes (rank, time-series rank, volatility-scaled change, steadiness, reversion, peer-relative trend, two-field spread, divergence from price, …) over the chosen fields, most regions first. Shapes whose Alphas score better are written more often as the task runs. No key, no budget.'
              : 'The chosen model writes 20 Alphas a call from your prompt and fields, and sees what came back.'}{' '}
            You can also reach region-agnostic Alphas from{' '}
            <Link to="/repair" className={LINK}>
              Repair
            </Link>
            : transplants and promotions.
          </p>
        </div>
      </Panel>
      {options.isError && <ErrorNotice error={options.error} title="Could not load the options" />}
      {options.isSuccess && !shapes && models.length === 0 && (
        <Notice
          tone="warn"
          title="This lab needs a model"
          action={
            <Button size="sm" render={<Link to="/ai/$tab" params={{ tab: 'models' }} />}>
              Set up a model
            </Button>
          }
        >
          Add a Key in LLM Integration and set up a model for it, with the limits your provider
          shows you.
        </Notice>
      )}
      <DatasetsPanel {...panel}>
        <div className="flex flex-col gap-4">
          <p className="text-body-compact text-pretty text-ink-subtle">
            Choose Datasets or Fields opens the All Regions market. There, More filters has Regions
            per field: keep to fields two or more regions carry, then tick the ones to use.
          </p>
          {!shapes && (
            <Fieldset
              legend="Prompt"
              hint="What the LLM is told first. Edits in LLM Prompts reach running tasks on their next call."
            >
              <PromptPicker
                kind={PROMPT_KIND}
                value={promptId}
                onChange={(next) => set({ promptId: next })}
              />
            </Fieldset>
          )}
        </div>
      </DatasetsPanel>

      <Panel title="Regions">
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-start gap-x-8 gap-y-4">
            <Fieldset legend="Delay">
              <Segmented
                label="Delay"
                items={[
                  { value: 0, label: '0' },
                  { value: 1, label: '1' },
                ]}
                value={draft.delay}
                onChange={(delay) => set({ delay, universe: '' })}
              />
            </Fieldset>
            <Fieldset
              legend="Universe"
              hint="BRAIN's region-agnostic sizes, each a universe per region. Random: each Alpha at a size drawn at random, the same in every region."
            >
              <Segmented
                label="Universe"
                items={SIZES.map((v) => ({ value: v, label: v }))}
                value={size}
                onChange={(next) => set({ size: next })}
              />
            </Fieldset>
            <Fieldset
              legend="Run in"
              hint="Each Alpha runs in every one of these that carries all its fields: two at least."
            >
              <Chips
                label="Regions"
                items={offered.map((o) => ({ value: o.region, label: o.region }))}
                value={regions}
                onChange={(next) => set({ regions: next })}
              />
            </Fieldset>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {regions.map((region) => {
              const o = offered.find((x) => x.region === region)
              const count = plan?.perRegion.find((p) => p.region === region)?.fields
              return (
                <Fieldset
                  key={region}
                  legend={`${region} universe`}
                  hint={count === undefined ? undefined : `${fmt.int(count)} of the fields here`}
                >
                  <span className="num text-body text-ink">{universeOf(region) || '—'}</span>
                  {o && size !== 'RANDOM' && !o.universes.includes(universeOf(region)) && (
                    <span className="text-body-compact text-pnl-negative">Not downloaded</span>
                  )}
                </Fieldset>
              )
            })}
          </div>
        </div>
      </Panel>

      {!shapes && <ResearchPicked />}
      <Panel title="Settings">
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-start gap-x-8 gap-y-4">
            {!shapes && (
              <Fieldset legend="Model">
                <Select
                  label="Model"
                  items={models.map((m) => ({
                    value: m.ref,
                    label: `${m.id} · ${providerLabel(m.provider)} · ${fmt.int(m.remainingToday)} left today${m.writes ? '' : ' · not for writing'}`,
                  }))}
                  value={model}
                  onChange={(v) => set({ model: v })}
                />
              </Fieldset>
            )}
            <CoresSetting value={cores} onChange={(next) => set({ cores: next })} />
            <SimulationsSetting
              value={draft.simulations}
              max={maxSimulations}
              placeholder="500"
              onChange={(next) => set({ simulations: next })}
            />
          </div>
          {shared && shared.length > 0 && (
            <NeutralizationPicker
              available={shared.map((n) => ({
                value: n,
                // BRAIN's own label where the All Regions market names it.
                label: allRegions.neutralizations.find((c) => c.value === n)?.label ?? n,
              }))}
              value={draft.neutralizations}
              onChange={(next) => set({ neutralizations: next })}
              hint="Only what every chosen region offers. None chosen draws from all of them; each Alpha gets one, the same in every region."
            />
          )}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Metric boxed label="Fields" value={fmt.int(plan?.fields)} hint="Chosen, ranked" />
            <Metric boxed label="Regions" value={fmt.int(regions.length)} />
            <Metric
              boxed
              label="LLM Calls"
              value={shapes ? 'None' : fmt.int(plan?.llmCalls)}
              hint={
                shapes ? 'The built-in shapes write' : '20 Alphas each, a simulation per region'
              }
            />
            <Metric
              boxed
              label="Single-region fields"
              value={fmt.int(plan?.lonely)}
              hint="Need another field beside them"
            />
          </div>
          {preview.isError && <ErrorNotice error={preview.error} title="Could not plan the task" />}
          {plan?.problems.map((m) => (
            <Notice key={m} tone="error" title={m} />
          ))}
          {plan?.warnings.map((m) => (
            <Notice key={m} tone="warn" title={m} />
          ))}
          {shapes && plan?.sample && plan.sample.length > 0 && (
            <Disclosure summary={`Sample · ${plan.sample.length} of the first call's Alphas`}>
              <pre className={PRE} role="region" aria-label="Sample Alphas">
                {plan.sample.join('\n')}
              </pre>
            </Disclosure>
          )}
          {!shapes && plan?.prompt && (
            <Disclosure
              summary={`Prompt · ${plan.prompt.name} · ~${fmt.int(plan.prompt.tokens)} tokens`}
            >
              <div className="flex flex-col gap-2">
                <pre className={PRE} role="region" aria-label="System prompt">
                  {plan.prompt.system}
                </pre>
                <pre className={PRE} role="region" aria-label="User prompt">
                  {plan.prompt.user}
                </pre>
              </div>
            </Disclosure>
          )}
        </div>
      </Panel>
    </Page>
  )
}

/** ARC: datasets to start from, and when an expression earns a real region-agnostic run. */
function ArcPanel({
  chosen,
  promote,
  delay,
  onDatasets,
  onPromote,
  onDelay,
}: {
  chosen: string[]
  promote: 'near' | 'strict' | 'off'
  delay: number
  onDatasets: (ids: string[]) => void
  onPromote: (promote: 'near' | 'strict' | 'off') => void
  onDelay: () => void
}) {
  const picks = useQuery({
    queryKey: ['region-agnostic-lab', 'picks'],
    queryFn: regionAgnosticLab.picks,
  })
  const data = picks.data
  const community = data?.community ?? []
  const roomy = data?.leastCrowded ?? []
  return (
    <Panel
      title="ARC: region-agnostic Alphas that pass in two regions"
      description="Each Alpha runs as an ordinary simulation in every chosen region first, which is cheap. When two regions pass every check but correlation (or one passes and another is within 7%), the lab runs it once as a real region-agnostic Alpha, the RA Parent ARC counts, unless every passing region already fails prod correlation. BRAIN needs one passing region under the prod limit."
    >
      <div className="flex flex-col gap-4">
        {delay !== 1 && (
          <Notice
            tone="error"
            title="Region-agnostic Alphas run at delay 1 only"
            action={
              <Button size="sm" onClick={onDelay}>
                Use delay 1
              </Button>
            }
          />
        )}
        <Fieldset
          legend="Run as region-agnostic"
          hint="Near tries more candidates (each RA run costs a simulation per region); Two pass only promotes sure ones."
        >
          <Segmented
            label="Run as region-agnostic"
            items={[
              { value: 'near' as const, label: 'Two pass, or one passes and one is near' },
              { value: 'strict' as const, label: 'Two pass' },
              { value: 'off' as const, label: 'Never (use Repair → Promote)' },
            ]}
            value={promote}
            onChange={onPromote}
          />
        </Fieldset>
        <Fieldset
          legend="Datasets the community reports work for ARC"
          hint="From the 1 October 2026 webinar and consultants' posts: pv1, fundamental17/23, other335, model38/110/138, analyst69, imbalance5, predictive_starmine, intraday_pv_feats, institutions6 and more. A starting point; the hypothesis matters more."
        >
          {picks.isError && <ErrorNotice error={picks.error} title="Could not read the datasets" />}
          {data && community.length === 0 && (
            <span className="text-body-compact text-ink-subtle">
              None of them is in your downloaded All Regions market yet. Sync the All Regions market
              (region ALL, delay 1) in Sync with BRAIN.
            </span>
          )}
          {community.length > 0 && (
            <div className="flex flex-col gap-2">
              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="primary"
                  onClick={() => onDatasets(community.map((d) => d.datasetId))}
                >
                  Use these {community.length}
                </Button>
                <Button
                  size="sm"
                  onClick={() =>
                    onDatasets([...new Set([...chosen, ...community.map((d) => d.datasetId)])])
                  }
                >
                  Add to my datasets
                </Button>
              </div>
              <span className="text-body-compact text-ink-muted">
                {community
                  .map(
                    (d) =>
                      `${d.datasetId}${d.crowding != null ? ` (${fmt.int(d.crowding)}/field)` : ''}`,
                  )
                  .join(' · ')}
              </span>
              {(data?.missing.length ?? 0) > 0 && (
                <span className="text-caption text-ink-subtle">
                  Not in your catalog: {data?.missing.join(', ')}
                </span>
              )}
            </div>
          )}
        </Fieldset>
        {roomy.length > 0 && (
          <Fieldset
            legend="Least crowded datasets in every region"
            hint="Fewest Alphas per field: where prod correlation has the most room."
          >
            <div className="flex flex-col gap-2">
              <div>
                <Button
                  size="sm"
                  onClick={() => onDatasets(roomy.slice(0, 10).map((d) => d.datasetId))}
                >
                  Use the 10 least crowded
                </Button>
              </div>
              <span className="text-body-compact text-ink-muted">
                {roomy
                  .slice(0, 20)
                  .map((d) => `${d.datasetId} (${fmt.int(d.crowding)}/field)`)
                  .join(' · ')}
              </span>
            </div>
          </Fieldset>
        )}
      </div>
    </Panel>
  )
}
