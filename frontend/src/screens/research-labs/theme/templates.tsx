/**
 * Templates the Current Theme Lab simulates: pick any number, beside the lab's own shapes or
 * instead of them. Each reads one data field ({x}) over a lookback the search tries ({d}).
 */

import { useQuery } from '@tanstack/react-query'
import type { components } from '@/api/generated'
import { http, qs } from '@/api/http'
import { fmt } from '@/lib/format'
import { Badge, Button, Checkbox, ErrorNotice, Field, Skeleton, Switch } from '@/ui/kit'

type Info = components['schemas']['ThemeTemplateInfo']

export function ThemeTemplatePicker({
  theme,
  value,
  onChange,
  shapes,
  onShapes,
}: {
  theme: string | null
  value: string[]
  onChange: (names: string[]) => void
  shapes: boolean
  onShapes: (on: boolean) => void
}) {
  const list = useQuery({
    queryKey: ['theme-lab', 'templates', theme],
    queryFn: () => http.get<Info[]>(`/api/theme-lab/templates${qs({ theme })}`),
    // Pass rates fill in once counted in the background.
    staleTime: 60_000,
    refetchInterval: (q) => (q.state.data?.some((t) => t.tried > 0) ? false : 30_000),
  })
  const all = list.data ?? []
  const available = all.filter((t) => t.available)
  const suggested = available.filter((t) => t.suggested).map((t) => t.name)
  const toggle = (name: string, on: boolean) =>
    onChange(on ? [...value, name] : value.filter((n) => n !== name))

  return (
    <Field
      label={`Templates (${fmt.int(value.length)} chosen)`}
      hint="{x} is the data field, {d} a lookback the search tries. Choose several; with none chosen the lab uses its own shapes."
    >
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" variant="secondary" onClick={() => onChange(suggested)}>
            Suggested ({fmt.int(suggested.length)})
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => onChange(available.filter((t) => t.lowTurnover).map((t) => t.name))}
          >
            Low turnover only
          </Button>
          <Button size="sm" variant="ghost" onClick={() => onChange(available.map((t) => t.name))}>
            All
          </Button>
          <Button size="sm" variant="ghost" onClick={() => onChange([])}>
            Clear
          </Button>
          <div className="ml-auto flex items-center gap-2 text-body-compact text-ink-muted">
            <Switch
              checked={shapes}
              onChange={onShapes}
              aria-label="Also search the lab's own shapes"
            />
            Also search the lab’s own shapes
          </div>
        </div>
        {list.isPending && <Skeleton label="Reading the templates" />}
        {list.isError && (
          <div className="flex flex-col gap-2">
            <ErrorNotice error={list.error} title="Could not read the templates" />
            <Button size="sm" variant="secondary" onClick={() => void list.refetch()}>
              Try again
            </Button>
          </div>
        )}
        <div className="grid grid-cols-1 gap-2 lg:grid-cols-2">
          {all.map((t) => (
            <div
              key={t.name}
              className={`flex flex-col gap-1 rounded-md border p-2.5 ${
                value.includes(t.name) ? 'border-primary' : 'border-hairline'
              } ${t.available ? '' : 'opacity-50'}`}
            >
              <Checkbox
                checked={value.includes(t.name)}
                disabled={!t.available}
                onChange={(on) => toggle(t.name, on)}
                label={
                  <span className="flex flex-wrap items-center gap-1.5">
                    <span className="font-medium text-ink">{t.name}</span>
                    {t.suggested && <Badge tone="profit">suggested</Badge>}
                    {t.lowTurnover && <Badge>low turnover</Badge>}
                    {!t.available && <Badge tone="outline">not on your account</Badge>}
                    {t.tried > 0 && (
                      <span className="num text-body-compact text-ink-subtle">
                        {fmt.pct(t.passRate, 0)} pass of {fmt.int(t.tried)}
                      </span>
                    )}
                  </span>
                }
              />
              <code
                className="truncate font-mono text-body-compact text-ink-muted"
                title={t.expression}
              >
                {t.expression}
              </code>
              <p className="text-body-compact text-ink-subtle">{t.about}</p>
            </div>
          ))}
        </div>
      </div>
    </Field>
  )
}
