/** Crowding history (backend `crowding`): datasets and fields filling up, from daily snapshots. */

import { queryOptions } from '@tanstack/react-query'
import type { components } from '@/api/generated'
import { http, qs } from '@/api/http'

type Schemas = components['schemas']
export type DatasetTrend = Schemas['DatasetTrend']
export type FieldTrend = Schemas['FieldTrend']

interface Market {
  region: string
  delay: number
  universe: string
  days: number
}

export const snapshotDays = queryOptions({
  queryKey: ['crowding', 'days'],
  queryFn: () => http.get<string[]>('/api/crowding/days'),
})

export const datasetTrends = (m: Market) =>
  queryOptions({
    queryKey: ['crowding', 'datasets', m],
    queryFn: () => http.get<DatasetTrend[]>(`/api/crowding/datasets${qs({ ...m, limit: 200 })}`),
  })

export const fieldTrends = (m: Market, datasetId: string | null) =>
  queryOptions({
    queryKey: ['crowding', 'fields', m, datasetId],
    queryFn: () =>
      http.get<FieldTrend[]>(`/api/crowding/fields${qs({ ...m, datasetId, limit: 200 })}`),
    enabled: datasetId !== null,
  })
