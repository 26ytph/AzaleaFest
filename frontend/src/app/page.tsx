'use client'

import dynamic from 'next/dynamic'
import { useEffect, useMemo, useState } from 'react'
import { useRouter } from 'next/navigation'
import Sidebar, { type CategoryFilter } from '@/components/Sidebar'
import { usePlaces } from '@/hooks/usePlaces'
import { useRecommendations } from '@/hooks/useRecommendations'
import { useTrips } from '@/hooks/useTrips'
import { api, getSessionId } from '@/lib/api'
import { tripsStore } from '@/lib/trips'
import type { RecommendResult } from '@/lib/types'

// Mapbox needs window.
const MapView = dynamic(() => import('@/components/Map'), {
  ssr: false,
  loading: () => (
    <div className="flex h-full w-full items-center justify-center text-slate-400">
      載入地圖…
    </div>
  ),
})

export default function HomePage() {
  const router = useRouter()
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [category, setCategory] = useState<CategoryFilter>('all')

  useEffect(() => {
    setSessionId(getSessionId())
    if (process.env.NEXT_PUBLIC_USE_MOCK === 'true') {
      tripsStore.seedSampleIfEmpty()
    }
  }, [])

  const { places, mutate: mutatePlaces } = usePlaces(sessionId)
  const { recommendations } = useRecommendations(
    sessionId,
    category,
    places.length > 0,
  )
  const { trips } = useTrips()

  const filteredRecs = useMemo<RecommendResult[]>(() => {
    if (category === 'all') return recommendations
    return recommendations.filter((r) => r.attraction.category === category)
  }, [recommendations, category])

  const handleDeletePlace = async (id: number) => {
    if (!sessionId) return
    if (!confirm('確定要從收藏中移除這個地點嗎？')) return
    await api.deletePlace(id, sessionId)
    mutatePlaces()
    if (selectedId === id) setSelectedId(null)
  }

  const handleAddRecommendation = async (rec: RecommendResult) => {
    if (!sessionId) return
    const a = rec.attraction
    await api.addPlace({
      session_id: sessionId,
      name: a.name,
      category: (a.category === 'food' || a.category === 'hotel'
        ? a.category
        : 'attraction') as 'food' | 'attraction' | 'hotel',
      lat: a.lat,
      lng: a.lng,
      address: a.address,
      description: a.description,
      source_type: 'manual',
      source_url: null,
    })
    mutatePlaces()
  }

  const handleCreateTrip = () => {
    router.push('/trips/new')
  }

  const handleAddPlaceToTrip = (_placeId: number) => {
    // Reserved for future quick-add flow; currently routed via wizard.
    router.push('/trips/new')
  }

  const handleDeleteTrip = (tripId: string) => {
    if (!confirm('確定要刪除這個行程嗎？')) return
    tripsStore.remove(tripId)
  }

  return (
    <main className="flex h-screen w-screen overflow-hidden">
      <Sidebar
        places={places}
        recommendations={filteredRecs}
        trips={trips}
        selectedId={selectedId}
        category={category}
        onCategoryChange={setCategory}
        onSelectPlace={setSelectedId}
        onDeletePlace={handleDeletePlace}
        onAddRecommendation={handleAddRecommendation}
        onCreateTrip={handleCreateTrip}
        onAddPlaceToTrip={handleAddPlaceToTrip}
        onDeleteTrip={handleDeleteTrip}
      />
      <div className="relative flex-1">
        <MapView
          places={places}
          recommendations={filteredRecs}
          selectedId={selectedId}
          onMarkerClick={(id) => setSelectedId(id)}
        />
      </div>
    </main>
  )
}
