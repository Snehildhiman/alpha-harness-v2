/** The learned models (backend `models`): status, training and predictions. */

import { queryOptions } from '@tanstack/react-query'
import type { components } from '@/api/generated'
import { http } from '@/api/http'

type Schemas = components['schemas']
export type ModelStatus = Schemas['ModelStatus']
export type TargetReport = Schemas['TargetReport']
export type Candidate = Schemas['Candidate']
export type Prediction = Schemas['Prediction']

export const modelStatus = queryOptions({
  queryKey: ['models', 'status'],
  queryFn: () => http.get<ModelStatus>('/api/models'),
})

export const trainModels = () => http.post<Schemas['TrainStarted']>('/api/models/train')

export const predict = (candidate: Candidate) =>
  http.post<Prediction[]>('/api/models/predict', candidate)
