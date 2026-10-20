/** The research library (backend `research`): papers from free feeds for the LLM labs. */

import { queryOptions } from '@tanstack/react-query'
import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { components } from '@/api/generated'
import { http, qs } from '@/api/http'

type Schemas = components['schemas']
export type Paper = Schemas['Paper']
export type PaperPage = Schemas['PaperPage']

export const paperPage = (q: {
  search?: string | undefined
  starred: boolean
  limit: number
  offset: number
}) =>
  queryOptions({
    queryKey: ['research', 'papers', q],
    queryFn: () => http.get<PaperPage>(`/api/research/papers${qs(q)}`),
  })

export const refreshFeeds = () => http.post<Record<string, number>>('/api/research/refresh')

export const starPaper = (id: number, on: boolean) =>
  http.put<Paper>(`/api/research/papers/${id}/star`, { on })

export interface PickedPaper {
  id: number
  title: string
}

/** Papers chosen on the Research screen for the next LLM lab task, kept across screens. */
export const useResearchPick = create<{
  picked: PickedPaper[]
  toggle: (paper: PickedPaper) => void
  clear: () => void
}>()(
  persist(
    (set) => ({
      picked: [],
      toggle: (paper) =>
        set((s) => ({
          picked: s.picked.some((p) => p.id === paper.id)
            ? s.picked.filter((p) => p.id !== paper.id)
            : [...s.picked, paper],
        })),
      clear: () => set({ picked: [] }),
    }),
    { name: 'ah-research-pick' },
  ),
)
