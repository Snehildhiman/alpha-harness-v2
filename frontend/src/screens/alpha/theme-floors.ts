/**
 * Keeps the check lists' theme rule in step with the theme calendar: the sub-regions a Power
 * Pool theme running today holds to a Sharpe floor (see `strictResult`).
 */

import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { themeCalendar } from '@/screens/types/api'
import { setThemeAreas } from './analysis'

export function useThemeFloors() {
  const calendar = useQuery(themeCalendar)
  useEffect(() => {
    const today = new Date().toISOString().slice(0, 10)
    const areas = new Set<string>()
    for (const rule of calendar.data ?? []) {
      if ((rule.powerPool ?? true) && rule.start <= today && today <= rule.end)
        for (const area of Object.keys(rule.subRegionSharpe ?? {})) areas.add(area.toUpperCase())
    }
    setThemeAreas(areas)
  }, [calendar.data])
}
