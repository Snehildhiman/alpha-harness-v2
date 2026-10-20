/** Submission Planner: which submittable Alphas to submit, and in what order. */

import type { components } from '@/api/generated'
import { http } from '@/api/http'

type Schemas = components['schemas']

export type PlannedPortfolio = Schemas['PlannedPortfolio']
export type Pick = Schemas['Pick']

const B = '/api/tools/submission-planner'

export const submissionPlanner = {
  plan: (taskIds: number[]) => http.post<PlannedPortfolio>(`${B}/plan`, { taskIds }),
  setSubmitted: (alphaId: string, submitted: boolean) =>
    http.post<void>(`${B}/submitted`, { alphaId, submitted }),
}
