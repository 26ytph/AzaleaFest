'use client'

import { useEffect, useState, useCallback } from 'react'
import { tripsStore } from '@/lib/trips'
import type { TripPlan } from '@/lib/trip-types'

export function useTrips() {
  const [trips, setTrips] = useState<TripPlan[]>([])

  const refresh = useCallback(() => {
    setTrips(tripsStore.list())
  }, [])

  useEffect(() => {
    refresh()
    const handler = () => refresh()
    window.addEventListener('wg:trips-changed', handler)
    window.addEventListener('storage', handler)
    return () => {
      window.removeEventListener('wg:trips-changed', handler)
      window.removeEventListener('storage', handler)
    }
  }, [refresh])

  return { trips, refresh }
}

export function useTrip(id: string | null) {
  const [trip, setTrip] = useState<TripPlan | null>(null)

  const refresh = useCallback(() => {
    if (!id) {
      setTrip(null)
      return
    }
    setTrip(tripsStore.get(id) ?? null)
  }, [id])

  useEffect(() => {
    refresh()
    const handler = () => refresh()
    window.addEventListener('wg:trips-changed', handler)
    return () => window.removeEventListener('wg:trips-changed', handler)
  }, [refresh])

  return { trip, refresh }
}
