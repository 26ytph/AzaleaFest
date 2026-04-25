'use client'

import { useEffect, useRef } from 'react'
import mapboxgl from 'mapbox-gl'
import 'mapbox-gl/dist/mapbox-gl.css'
import type { Place, RecommendResult } from '@/lib/types'

export interface MapProps {
  places: Place[]
  recommendations: RecommendResult[]
  selectedId: number | null
  onMarkerClick: (id: number, type: 'place' | 'recommendation') => void
}

const TAIPEI_CENTER: [number, number] = [121.5654, 25.033]
const TOKEN = process.env.NEXT_PUBLIC_MAPBOX_TOKEN

export default function MapView({
  places,
  recommendations,
  selectedId,
  onMarkerClick,
}: MapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<mapboxgl.Map | null>(null)
  const markersRef = useRef<globalThis.Map<string, mapboxgl.Marker>>(new globalThis.Map())

  // init once
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return
    if (TOKEN) mapboxgl.accessToken = TOKEN

    mapRef.current = new mapboxgl.Map({
      container: containerRef.current,
      style: 'mapbox://styles/mapbox/light-v11',
      center: TAIPEI_CENTER,
      zoom: 12,
    })
    mapRef.current.addControl(
      new mapboxgl.NavigationControl({ showCompass: false }),
      'top-right',
    )

    return () => {
      mapRef.current?.remove()
      mapRef.current = null
      markersRef.current.clear()
    }
  }, [])

  // sync markers
  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    const want = new Set<string>()

    const buildEl = (
      kind: 'place' | 'recommendation',
      isSelected: boolean,
      legal: 'legal' | 'illegal' | 'unknown' | null | undefined,
      onClick: () => void,
    ) => {
      const el = document.createElement('div')
      el.className = 'wg-marker'
      el.dataset.kind = kind
      el.dataset.selected = String(isSelected)
      if (legal) {
        const badge = document.createElement('span')
        badge.className = `badge ${legal}`
        el.appendChild(badge)
      }
      el.addEventListener('click', (e) => {
        e.stopPropagation()
        onClick()
      })
      return el
    }

    const upsert = (key: string, lng: number, lat: number, el: HTMLElement) => {
      want.add(key)
      const existing = markersRef.current.get(key)
      if (existing) {
        existing.remove()
        markersRef.current.delete(key)
      }
      const marker = new mapboxgl.Marker({ element: el }).setLngLat([lng, lat]).addTo(map)
      markersRef.current.set(key, marker)
    }

    for (const p of places) {
      const el = buildEl(
        'place',
        selectedId === p.id,
        p.category === 'hotel' ? p.hotel_legal_status : null,
        () => onMarkerClick(p.id, 'place'),
      )
      upsert(`p:${p.id}`, p.lng, p.lat, el)
    }

    for (const r of recommendations) {
      const el = buildEl(
        'recommendation',
        selectedId === r.attraction.id,
        null,
        () => onMarkerClick(r.attraction.id, 'recommendation'),
      )
      upsert(`r:${r.attraction.id}`, r.attraction.lng, r.attraction.lat, el)
    }

    for (const [key, marker] of markersRef.current) {
      if (!want.has(key)) {
        marker.remove()
        markersRef.current.delete(key)
      }
    }
  }, [places, recommendations, selectedId, onMarkerClick])

  // flyTo selection
  useEffect(() => {
    if (!mapRef.current || selectedId == null) return
    const target =
      places.find((p) => p.id === selectedId) ??
      recommendations.find((r) => r.attraction.id === selectedId)?.attraction
    if (!target) return
    mapRef.current.flyTo({ center: [target.lng, target.lat], zoom: 14, speed: 1.2 })
  }, [selectedId, places, recommendations])

  return (
    <div className="relative h-full w-full">
      <div ref={containerRef} className="absolute inset-0 h-full" />
      {!TOKEN && (
        <div className="absolute left-3 top-3 rounded bg-amber-100 px-3 py-2 text-xs text-amber-800 shadow">
          缺少 NEXT_PUBLIC_MAPBOX_TOKEN，地圖底圖無法載入。
        </div>
      )}
    </div>
  )
}
