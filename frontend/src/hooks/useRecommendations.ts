'use client'

import useSWR from 'swr'
import { api } from '@/lib/api'
import type { RecommendResult } from '@/lib/types'

export function useRecommendations(
  sessionId: string | null,
  category: string,
  enabled: boolean,
) {
  const { data, error, isLoading, mutate } = useSWR<RecommendResult[]>(
    enabled && sessionId ? ['recommend', sessionId, category] : null,
    ([, sid, cat]) => api.getRecommendations(sid as string, cat as string, 6),
    {
      revalidateOnFocus: false,
      keepPreviousData: true,
    },
  )

  return {
    recommendations: data ?? [],
    isLoading,
    error,
    mutate,
  }
}
