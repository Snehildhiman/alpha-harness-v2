/** Alpha Types: every stored Alpha judged by its own type's rules (backend `separation`). */

import { queryOptions } from '@tanstack/react-query'
import type { components } from '@/api/generated'
import { http, qs } from '@/api/http'

type Schemas = components['schemas']
export type TypeSummary = Schemas['Summary']
export type TabPage = Schemas['TabPage']
export type TabRow = Schemas['TabRow']

/** The backend's kinds; the URL spells `power_pool` as `power-pool`. */
export type Kind = 'regular' | 'ra' | 'power_pool' | 'theme' | 'super'
export type Verdict = 'submittable' | 'pending' | 'refused' | 'submitted'
export type TypeSort = 'sharpe' | 'fitness' | 'turnover' | 'returns' | 'margin' | 'date_created'

export const typeSummary = queryOptions({
  queryKey: ['separation', 'summary'],
  queryFn: () => http.get<TypeSummary>('/api/separation/summary'),
})

export const typeTab = (q: {
  tab: Kind
  verdict: Verdict
  sort: TypeSort
  limit: number
  offset: number
}) =>
  queryOptions({
    queryKey: ['separation', 'alphas', q],
    queryFn: () => http.get<TabPage>(`/api/separation/alphas${qs(q)}`),
  })
