/** Scorecards (backend `scorecards`): which parts of an Alpha run hot or cold on a metric. */

import { queryOptions } from '@tanstack/react-query'
import type { components } from '@/api/generated'
import { http, qs } from '@/api/http'

type Schemas = components['schemas']
export type CardPage = Schemas['CardPage']
export type CardRow = Schemas['CardRow']

export type Part =
  | 'operator'
  | 'pair'
  | 'field'
  | 'dataset'
  | 'category'
  | 'lookback'
  | 'neutralization'
  | 'region'
export type Metric =
  | 'prod_corr'
  | 'power_pool_corr'
  | 'self_corr'
  | 'check:PROD_CORRELATION'
  | 'check:POWER_POOL_CORRELATION'
  | 'check:SELF_CORRELATION'
  | 'sharpe'
  | 'fitness'

export const scorecards = (q: { part: Part; metric: Metric; minAlphas: number; limit: number }) =>
  queryOptions({
    queryKey: ['scorecards', q],
    queryFn: () => http.get<CardPage>(`/api/scorecards${qs(q)}`),
  })
