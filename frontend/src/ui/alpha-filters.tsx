/**
 * Filters for lists of Alphas: region, dataset, data category, universe, neutralization,
 * figure bounds and a text search. Choices come with counts from the list's own facets, so
 * only values that are present are offered. "Any" (the empty value) means no filter.
 */

import { XIcon } from 'lucide-react'
import { useEffect, useState } from 'react'
import { fmt } from '@/lib/format'
import { Button, Checkbox, Input } from './kit'
import { Select } from './overlay'

export interface AlphaFilters {
  region?: string | undefined
  dataset?: string | undefined
  category?: string | undefined
  universe?: string | undefined
  neutralization?: string | undefined
  minSharpe?: number | undefined
  minFitness?: number | undefined
  maxTurnover?: number | undefined
  search?: string | undefined
  /** Reads a field of one of BRAIN's theme datasets. */
  theme?: boolean | undefined
  /** Fits a regular theme running today (e.g. a turnover range). */
  fitsTheme?: boolean | undefined
  // Index signature so it can go straight into a query string.
  [key: string]: string | number | boolean | undefined
}

export interface FacetList {
  value: string
  alphas: number
}

export interface Facets {
  regions?: FacetList[]
  datasets?: FacetList[]
  categories?: FacetList[]
  universes?: FacetList[]
  neutralizations?: FacetList[]
}

const ANY = '__any__'

function FacetSelect({
  label,
  items,
  value,
  onChange,
}: {
  label: string
  items: FacetList[] | undefined
  value: string | undefined
  onChange: (value: string | undefined) => void
}) {
  if (!items?.length && !value) return null
  const choices = [
    { value: ANY, label: `Any ${label.toLowerCase()}` },
    ...(items ?? []).map((f) => ({ value: f.value, label: `${f.value} (${fmt.int(f.alphas)})` })),
  ]
  return (
    <Select
      label={label}
      mono
      items={choices}
      value={value ?? ANY}
      onChange={(v) => onChange(v === ANY ? undefined : v)}
    />
  )
}

/** A number box that only reports a finished number (or a cleared box). */
function Bound({
  label,
  value,
  onChange,
  step = 0.1,
  scale = 1,
}: {
  label: string
  value: number | undefined
  onChange: (value: number | undefined) => void
  step?: number
  /** Shown as value × scale (turnover is a fraction, shown in percent). */
  scale?: number
}) {
  const shown = value === undefined ? '' : String(Math.round(value * scale * 1e6) / 1e6)
  const [text, setText] = useState(shown)
  useEffect(() => setText(shown), [shown])
  return (
    <Input
      aria-label={label}
      placeholder={label}
      type="number"
      step={step}
      className="w-32"
      value={text}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => {
        const n = Number(text)
        onChange(text.trim() === '' || !Number.isFinite(n) ? undefined : n / scale)
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
      }}
    />
  )
}

export function AlphaFilterBar({
  value,
  onChange,
  facets,
  figures = true,
  themeFit = false,
}: {
  value: AlphaFilters
  onChange: (value: AlphaFilters) => void
  facets?: Facets | undefined
  /** Offer Sharpe / fitness / turnover bounds. */
  figures?: boolean
  /** Offer "fits a regular theme running today". */
  themeFit?: boolean
}) {
  const set = (patch: Partial<AlphaFilters>) => {
    const next: AlphaFilters = { ...value, ...patch }
    for (const k of Object.keys(next) as (keyof AlphaFilters)[])
      if (next[k] === undefined || next[k] === '' || next[k] === false) delete next[k]
    onChange(next)
  }
  const [search, setSearch] = useState(value.search ?? '')
  useEffect(() => setSearch(value.search ?? ''), [value.search])
  const active = Object.keys(value).length > 0
  return (
    <div className="flex flex-wrap items-center gap-2">
      <FacetSelect
        label="Region"
        items={facets?.regions}
        value={value.region}
        onChange={(region) => set({ region })}
      />
      <FacetSelect
        label="Dataset"
        items={facets?.datasets}
        value={value.dataset}
        onChange={(dataset) => set({ dataset })}
      />
      <FacetSelect
        label="Category"
        items={facets?.categories}
        value={value.category}
        onChange={(category) => set({ category })}
      />
      <FacetSelect
        label="Universe"
        items={facets?.universes}
        value={value.universe}
        onChange={(universe) => set({ universe })}
      />
      <FacetSelect
        label="Neutralization"
        items={facets?.neutralizations}
        value={value.neutralization}
        onChange={(neutralization) => set({ neutralization })}
      />
      {figures && (
        <>
          <Bound
            label="Min Sharpe"
            value={value.minSharpe}
            onChange={(minSharpe) => set({ minSharpe })}
          />
          <Bound
            label="Min fitness"
            value={value.minFitness}
            onChange={(minFitness) => set({ minFitness })}
          />
          <Bound
            label="Max turnover %"
            step={1}
            scale={100}
            value={value.maxTurnover}
            onChange={(maxTurnover) => set({ maxTurnover })}
          />
        </>
      )}
      <Input
        aria-label="Search expressions"
        placeholder="Search expression or id"
        className="w-56"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        onBlur={() => set({ search: search.trim() || undefined })}
        onKeyDown={(e) => {
          if (e.key === 'Enter') set({ search: search.trim() || undefined })
        }}
      />
      <Checkbox
        label="Theme datasets"
        checked={Boolean(value.theme)}
        onChange={(on) => set({ theme: on || undefined })}
      />
      {themeFit && (
        <Checkbox
          label="Fits a running theme"
          checked={Boolean(value.fitsTheme)}
          onChange={(on) => set({ fitsTheme: on || undefined })}
        />
      )}
      {active && (
        <Button variant="ghost" size="sm" onClick={() => onChange({})}>
          <XIcon aria-hidden />
          Clear filters
        </Button>
      )}
    </div>
  )
}
