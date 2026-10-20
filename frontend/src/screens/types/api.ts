/** Alpha Types: every stored Alpha judged by its own type's rules (backend `separation`). */

import { queryOptions } from '@tanstack/react-query'
import type { components } from '@/api/generated'
import { http, qs } from '@/api/http'
import type { AlphaFilters } from '@/ui/alpha-filters'

type Schemas = components['schemas']
export type TypeSummary = Schemas['Summary']
export type TabPage = Schemas['TabPage']
export type TabRow = Schemas['TabRow']

/** The backend's kinds; the URL spells `power_pool` as `power-pool`. */
export type Kind = 'regular' | 'ra' | 'power_pool' | 'theme' | 'super'
export type Verdict = 'submittable' | 'recheck' | 'pending' | 'refused' | 'submitted'
export type TypeSort = 'sharpe' | 'fitness' | 'turnover' | 'returns' | 'margin' | 'date_created'

export const typeSummary = queryOptions({
  queryKey: ['separation', 'summary'],
  queryFn: () => http.get<TypeSummary>('/api/separation/summary'),
})

export type TabFacets = Schemas['TabFacets']

export const typeFacets = (tab: Kind, verdict: Verdict) =>
  queryOptions({
    queryKey: ['separation', 'facets', tab, verdict],
    queryFn: () => http.get<TabFacets>(`/api/separation/facets${qs({ tab, verdict })}`),
  })

export const typeTab = (
  q: {
    tab: Kind
    verdict: Verdict
    sort: TypeSort
    limit: number
    offset: number
  } & AlphaFilters,
) =>
  queryOptions({
    queryKey: ['separation', 'alphas', q],
    queryFn: () => http.get<TabPage>(`/api/separation/alphas${qs(q)}`),
  })

export type ThemeRule = Schemas['ThemeRule']

export const themeCalendar = queryOptions({
  queryKey: ['separation', 'themes'],
  queryFn: () => http.get<ThemeRule[]>('/api/separation/themes'),
})

export const saveThemes = (rules: ThemeRule[]) =>
  http.put<ThemeRule[]>('/api/separation/themes', rules)

export const recheck = (body: {
  tab: Kind
  verdict: Verdict
  limit: number
  filters?: AlphaFilters
}) => http.post<Schemas['RecheckStarted']>('/api/separation/recheck', body)
