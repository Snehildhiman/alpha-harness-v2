/** Repair (backend `repair`): near-misses, ranked variants, and queuing the best of them. */

import { queryOptions } from '@tanstack/react-query'
import type { components } from '@/api/generated'
import { http, qs } from '@/api/http'

type Schemas = components['schemas']
export type NearMiss = Schemas['NearMiss']
export type RepairPlan = Schemas['RepairPlan']
export type RepairVariant = Schemas['RepairVariant']
export type RepairKind = 'regular' | 'ra' | 'power_pool' | 'theme' | 'super'

export const nearMisses = (tab: RepairKind | null) =>
  queryOptions({
    queryKey: ['repair', 'near', tab],
    queryFn: () => http.get<NearMiss[]>(`/api/repair/near-misses${qs({ tab })}`),
  })

export const repairPlan = (alphaId: string | null) =>
  queryOptions({
    queryKey: ['repair', 'plan', alphaId],
    queryFn: () => http.post<RepairPlan>('/api/repair/plan', { alphaId }),
    enabled: alphaId !== null,
    staleTime: 60_000,
  })

export const queueRepair = (body: { alphaId: string; take: number }) =>
  http.post<Schemas['AddedTask']>('/api/repair/tasks', body)

export type TransplantPlan = Schemas['TransplantPlan']
export type TransplantRow = Schemas['TransplantRow']

export const transplantPlan = (region: string | null) =>
  queryOptions({
    queryKey: ['repair', 'transplants', region],
    queryFn: () => http.get<TransplantPlan>(`/api/repair/transplants${qs({ region })}`),
    staleTime: 60_000,
  })

export const queueTransplants = (body: { take: number; region: string | null }) =>
  http.post<Schemas['AddedTask']>('/api/repair/transplants/tasks', body)
