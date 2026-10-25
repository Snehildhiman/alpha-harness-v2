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
    // Your own calendar day, not UTC's: a theme opening on the 26th has opened for you at
    // midnight, while UTC still reads the 25th until 05:30 in India.
    const now = new Date()
    const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
    const areas = new Set<string>()
    for (const rule of calendar.data ?? []) {
      if ((rule.powerPool ?? true) && rule.start <= today && today <= rule.end)
        for (const area of Object.keys(rule.subRegionSharpe ?? {})) areas.add(area.toUpperCase())
    }
    setThemeAreas(areas)
  }, [calendar.data])
}
