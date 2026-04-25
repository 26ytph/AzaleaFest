'use client'

import useSWR from 'swr'
import { api } from '@/lib/api'
import type { Place } from '@/lib/types'

export function usePlaces(sessionId: string | null) {
  const { data, error, isLoading, mutate } = useSWR<Place[]>(
    sessionId ? ['places', sessionId] : null,
    ([, sid]) => api.getPlaces(sid as string),
    {
      revalidateOnFocus: true,
      refreshInterval: 5000, // Line bot 寫入後 5 秒內自動同步
      keepPreviousData: true,
    },
  )

  return {
    places: data ?? [],
    isLoading,
    error,
    mutate,
  }
}
