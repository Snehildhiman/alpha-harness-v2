/** Repair (backend `repair`): near-misses, ranked variants, and queuing the best of them. */

import { queryOptions } from '@tanstack/react-query'
import type { components } from '@/api/generated'
import { http, qs } from '@/api/http'
import type { AlphaFilters } from '@/ui/alpha-filters'

type Schemas = components['schemas']
export type NearMiss = Schemas['NearMiss']
export type RepairPlan = Schemas['RepairPlan']
export type RepairVariant = Schemas['RepairVariant']
export type RepairKind = 'regular' | 'ra' | 'power_pool' | 'theme' | 'super'

export const nearMisses = (tab: RepairKind | null, filters: AlphaFilters = {}) =>
  queryOptions({
    queryKey: ['repair', 'near', tab, filters],
    queryFn: () => http.get<NearMiss[]>(`/api/repair/near-misses${qs({ tab, ...filters })}`),
  })

export const nearMissFacets = (tab: RepairKind | null) =>
  queryOptions({
    queryKey: ['repair', 'near-facets', tab],
    queryFn: () => http.get<Schemas['TabFacets']>(`/api/repair/near-misses/facets${qs({ tab })}`),
  })

export type RankBy = 'pass' | 'sharpe' | 'fitness'

export const repairPlan = (alphaId: string | null, rankBy: RankBy = 'pass') =>
  queryOptions({
    queryKey: ['repair', 'plan', alphaId, rankBy],
    queryFn: () => http.post<RepairPlan>('/api/repair/plan', { alphaId, rankBy }),
    enabled: alphaId !== null,
    staleTime: 60_000,
  })

export const queueRepair = (body: { alphaId: string; take: number; rankBy: RankBy }) =>
  http.post<Schemas['AddedTask']>('/api/repair/tasks', body)

export type TransplantPlan = Schemas['TransplantPlan']
export type TransplantRow = Schemas['TransplantRow']

export type TransplantKind = 'regular' | 'power_pool'

export const transplantPlan = (
  region: string | null,
  kind: TransplantKind | null = null,
  filters: AlphaFilters = {},
) =>
  queryOptions({
    queryKey: ['repair', 'transplants', region, kind, filters],
    queryFn: () =>
      http.get<TransplantPlan>(`/api/repair/transplants${qs({ ...filters, region, kind })}`),
    staleTime: 60_000,
  })

export const queueTransplants = (body: {
  take: number
  region: string | null
  kind: TransplantKind | null
  filters?: AlphaFilters
}) => http.post<Schemas['AddedTask']>('/api/repair/transplants/tasks', body)

export type PromotionPlan = Schemas['PromotionPlan']
export type PromotionRow = Schemas['PromotionRow']

/** `regions`: passing in two regions already. `glb`: passing or submitted Global alphas. */
export type PromotionSource = 'regions' | 'glb'

export const promotionPlan = (source: PromotionSource = 'regions') =>
  queryOptions({
    queryKey: ['repair', 'promotions', source],
    queryFn: () => http.get<PromotionPlan>(`/api/repair/promotions?source=${source}`),
    staleTime: 60_000,
  })

export const queuePromotions = (body: {
  universe: string
  delay: number
  take: number
  source?: PromotionSource
}) => http.post<Schemas['AddedTask']>('/api/repair/promotions/tasks', body)

export type AutopilotStatus = Schemas['AutopilotStatus']

export const autopilotStatus = queryOptions({
  queryKey: ['autopilot'],
  queryFn: () => http.get<AutopilotStatus>('/api/autopilot'),
  refetchInterval: 60_000,
})

export const autopilotRound = () => http.post<AutopilotStatus>('/api/autopilot/run', {})

export const transplantFacets = queryOptions({
  queryKey: ['repair', 'transplant-facets'],
  queryFn: () => http.get<Schemas['TabFacets']>('/api/repair/transplants/facets'),
})
