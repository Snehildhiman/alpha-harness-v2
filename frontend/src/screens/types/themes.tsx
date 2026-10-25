/**
 * The theme calendar, as BRAIN publishes it. The Current Theme tab tests every Power Pool
 * Alpha against whichever Power Pool rule is running today; a regular theme (such as a
 * turnover range) is shown on the Regular and Region Agnostic tabs. Rules are typed in here.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { PlusIcon, Trash2Icon } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Button, Disclosure, ErrorNotice, Field, Input, Switch } from '@/ui/kit'
import { saveThemes, type ThemeRule, themeCalendar } from './api'

const blank = (): ThemeRule => {
  const today = new Date().toISOString().slice(0, 10)
  return {
    name: '',
    start: today,
    end: today,
    delay: 1,
    categories: [],
    singleCategory: true,
    noGrouping: true,
    powerPool: true,
  }
}

function RuleRow({
  rule,
  onChange,
  onRemove,
}: {
  rule: ThemeRule
  onChange: (rule: ThemeRule) => void
  onRemove: () => void
}) {
  const [categories, setCategories] = useState((rule.categories ?? []).join(', '))
  return (
    <div className="flex flex-col gap-3 rounded-md border border-hairline p-3">
      <div className="grid grid-cols-1 items-end gap-3 lg:grid-cols-[2fr_1fr_1fr_80px_2fr_auto_auto_auto]">
        <Field label="Name">
          <Input value={rule.name} onChange={(e) => onChange({ ...rule, name: e.target.value })} />
        </Field>
        <Field label="From">
          <Input
            type="date"
            value={rule.start}
            onChange={(e) => onChange({ ...rule, start: e.target.value })}
          />
        </Field>
        <Field label="To">
          <Input
            type="date"
            value={rule.end}
            onChange={(e) => onChange({ ...rule, end: e.target.value })}
          />
        </Field>
        <Field label="Delay">
          <Input
            type="number"
            min={0}
            max={1}
            value={rule.delay ?? ''}
            onChange={(e) =>
              onChange({ ...rule, delay: e.target.value === '' ? null : Number(e.target.value) })
            }
          />
        </Field>
        <Field label="Data categories" hint="Comma-separated, e.g. analyst, model, news">
          <Input
            value={categories}
            onChange={(e) => {
              setCategories(e.target.value)
              onChange({
                ...rule,
                categories: e.target.value
                  .split(',')
                  .map((c) => c.trim())
                  .filter(Boolean),
              })
            }}
          />
        </Field>
        <div className="flex h-8 items-center gap-2 text-body-compact text-ink-muted">
          <Switch
            checked={rule.singleCategory}
            onChange={(on) => onChange({ ...rule, singleCategory: on })}
            aria-label="Single data category"
          />
          Single category
        </div>
        <div className="flex h-8 items-center gap-2 text-body-compact text-ink-muted">
          <Switch
            checked={rule.noGrouping ?? true}
            onChange={(on) => onChange({ ...rule, noGrouping: on })}
            aria-label="No group operators or grouping fields"
          />
          No grouping
        </div>
        <Button variant="ghost" size="icon-sm" aria-label="Remove this theme" onClick={onRemove}>
          <Trash2Icon />
        </Button>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex h-8 items-center gap-2 text-body-compact text-ink-muted">
          <Switch
            checked={rule.powerPool ?? true}
            onChange={(on) => onChange({ ...rule, powerPool: on })}
            aria-label="Power Pool theme"
          />
          Power Pool theme (off: for regular Alphas)
        </div>
        <Field label="Regions" hint="Comma-separated; empty: any">
          <Input
            className="w-36"
            defaultValue={(rule.regions ?? []).join(', ')}
            onBlur={(e) =>
              onChange({
                ...rule,
                regions: e.target.value
                  .split(',')
                  .map((r) => r.trim().toUpperCase())
                  .filter(Boolean),
              })
            }
          />
        </Field>
        <Field label="Turnover from %">
          <Input
            type="number"
            className="w-24"
            value={rule.turnoverMin == null ? '' : Math.round(rule.turnoverMin * 100)}
            onChange={(e) =>
              onChange({
                ...rule,
                turnoverMin: e.target.value === '' ? null : Number(e.target.value) / 100,
              })
            }
          />
        </Field>
        <Field label="to %">
          <Input
            type="number"
            className="w-24"
            value={rule.turnoverMax == null ? '' : Math.round(rule.turnoverMax * 100)}
            onChange={(e) =>
              onChange({
                ...rule,
                turnoverMax: e.target.value === '' ? null : Number(e.target.value) / 100,
              })
            }
          />
        </Field>
        <Field label="Multiplier">
          <Input
            type="number"
            step={0.1}
            className="w-24"
            value={rule.multiplier ?? ''}
            onChange={(e) =>
              onChange({
                ...rule,
                multiplier: e.target.value === '' ? null : Number(e.target.value),
              })
            }
          />
        </Field>
        <Field
          label="Sub-region Sharpe above"
          hint="GLB only, e.g. AMER 1 for “AMER Sharpe > 1”; empty: none"
        >
          <Input
            className="w-40"
            placeholder="AMER 1"
            defaultValue={Object.entries(rule.subRegionSharpe ?? {})
              .map(([area, floor]) => `${area} ${floor}`)
              .join(', ')}
            onBlur={(e) =>
              onChange({
                ...rule,
                subRegionSharpe: Object.fromEntries(
                  e.target.value
                    .split(',')
                    .map((part) => part.trim().split(/\s+/))
                    .filter(([area, floor]) => area && floor && !Number.isNaN(Number(floor)))
                    .map(([area, floor]) => [String(area).toUpperCase(), Number(floor)]),
                ),
              })
            }
          />
        </Field>
      </div>
      <Field
        label="Recommended datasets"
        hint="Comma-separated dataset ids from the announcement; the Current Theme Lab starts from these"
      >
        <Input
          defaultValue={(rule.datasets ?? []).join(', ')}
          onBlur={(e) =>
            onChange({
              ...rule,
              datasets: e.target.value
                .split(',')
                .map((d) => d.trim())
                .filter(Boolean),
            })
          }
        />
      </Field>
    </div>
  )
}

export function ThemeCalendar() {
  const client = useQueryClient()
  const saved = useQuery(themeCalendar)
  const [rules, setRules] = useState<ThemeRule[] | null>(null)
  useEffect(() => {
    if (saved.data && rules === null) setRules(saved.data)
  }, [saved.data, rules])
  const save = useMutation({
    mutationFn: saveThemes,
    onSuccess: (data) => {
      setRules(data)
      client.setQueryData(themeCalendar.queryKey, data)
      void client.invalidateQueries({ queryKey: ['separation'] })
    },
  })
  const list = rules ?? []
  const dirty = JSON.stringify(list) !== JSON.stringify(saved.data ?? [])

  return (
    <Disclosure summary={`Theme calendar (${list.length})`}>
      <div className="flex flex-col gap-3">
        <p className="text-body text-ink-subtle">
          Copy each theme from BRAIN’s Power Pool calendar. The rule running today decides the
          Current Theme tab.
        </p>
        {saved.isError && <ErrorNotice error={saved.error} title="Could not read the calendar" />}
        {save.isError && <ErrorNotice error={save.error} title="Could not save the calendar" />}
        {list.map((rule, i) => (
          <RuleRow
            key={i}
            rule={rule}
            onChange={(next) => setRules(list.map((r, j) => (j === i ? next : r)))}
            onRemove={() => setRules(list.filter((_, j) => j !== i))}
          />
        ))}
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => setRules([...list, blank()])}>
            <PlusIcon aria-hidden />
            Add theme
          </Button>
          <Button
            variant="primary"
            disabled={!dirty || list.some((r) => !r.name.trim())}
            loading={save.isPending}
            onClick={() => save.mutate(list)}
          >
            Save calendar
          </Button>
        </div>
      </div>
    </Disclosure>
  )
}
