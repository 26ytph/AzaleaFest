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

const CATEGORY_LABEL: Record<string, string> = {
  food: '🍽️ 美食',
  attraction: '🏛️ 景點',
  hotel: '🏨 住宿',
}

const HOTEL_BADGE: Record<string, string> = {
  legal: '🛡️ 合法旅宿',
  illegal: '⚠️ 疑似非法日租',
  unknown: '❓ 待確認',
}

function escapeHtml(s: string | null | undefined): string {
  if (!s) return ''
  return s.replace(/[&<>"']/g, (c) => {
    switch (c) {
      case '&': return '&amp;'
      case '<': return '&lt;'
      case '>': return '&gt;'
      case '"': return '&quot;'
      default: return '&#39;'
    }
  })
}

function buildPlacePopup(p: Place): string {
  const parts: string[] = []
  parts.push(`<div class="wg-pop-title">${escapeHtml(p.name)}</div>`)
  parts.push(`<div class="wg-pop-cat">${CATEGORY_LABEL[p.category] ?? ''}</div>`)
  if (p.address) parts.push(`<div class="wg-pop-addr">${escapeHtml(p.address)}</div>`)
  if (p.description) parts.push(`<div class="wg-pop-desc">${escapeHtml(p.description)}</div>`)
  if (p.category === 'hotel' && p.hotel_legal_status) {
    parts.push(`<div class="wg-pop-hotel ${p.hotel_legal_status}">${HOTEL_BADGE[p.hotel_legal_status]}</div>`)
  }
  return `<div class="wg-pop">${parts.join('')}</div>`
}

function buildRecPopup(r: RecommendResult): string {
  const a = r.attraction
  const parts: string[] = []
  parts.push(`<div class="wg-pop-title">${escapeHtml(a.name)}</div>`)
  parts.push(`<div class="wg-pop-cat">${CATEGORY_LABEL[a.category] ?? '📍 推薦'}</div>`)
  if (a.address) parts.push(`<div class="wg-pop-addr">${escapeHtml(a.address)}</div>`)
  if (r.reason) parts.push(`<div class="wg-pop-reason">「${escapeHtml(r.reason)}」</div>`)
  if (a.tags?.length) {
    parts.push(
      `<div class="wg-pop-tags">${a.tags
        .slice(0, 5)
        .map((t) => `<span>#${escapeHtml(t)}</span>`)
        .join(' ')}</div>`,
    )
  }
  return `<div class="wg-pop">${parts.join('')}</div>`
}

export default function MapView({
  places,
  recommendations,
  selectedId,
  onMarkerClick,
}: MapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<mapboxgl.Map | null>(null)
  const markersRef = useRef<globalThis.Map<string, mapboxgl.Marker>>(new globalThis.Map())
  const popupsRef = useRef<globalThis.Map<string, mapboxgl.Popup>>(new globalThis.Map())

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

    const ref = mapRef
    const markers = markersRef
    const popups = popupsRef
    return () => {
      ref.current?.remove()
      ref.current = null
      markers.current.clear()
      popups.current.clear()
    }
  }, [])

  // sync markers + popups
  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    const want = new Set<string>()

    const setup = (
      key: string,
      lng: number,
      lat: number,
      kind: 'place' | 'recommendation',
      isSelected: boolean,
      legal: 'legal' | 'illegal' | 'unknown' | null | undefined,
      popupHtml: string,
      onClick: () => void,
    ) => {
      want.add(key)

      // marker element
      const el = document.createElement('div')
      el.className = 'wg-marker'
      el.dataset.kind = kind
      el.dataset.selected = String(isSelected)
      if (legal) {
        const badge = document.createElement('span')
        badge.className = `badge ${legal}`
        el.appendChild(badge)
      }

      const popup = new mapboxgl.Popup({
        offset: 16,
        closeButton: false,
        closeOnClick: false,
        className: 'wg-popup',
      }).setHTML(popupHtml)

      el.addEventListener('mouseenter', () => {
        popup.setLngLat([lng, lat]).addTo(map)
      })
      el.addEventListener('mouseleave', () => {
        if (!isSelected) popup.remove()
      })
      el.addEventListener('click', (e) => {
        e.stopPropagation()
        popup.setLngLat([lng, lat]).addTo(map)
        onClick()
      })

      // remove existing
      const existingMarker = markersRef.current.get(key)
      if (existingMarker) existingMarker.remove()
      const existingPopup = popupsRef.current.get(key)
      if (existingPopup) existingPopup.remove()

      const marker = new mapboxgl.Marker({ element: el }).setLngLat([lng, lat]).addTo(map)
      markersRef.current.set(key, marker)
      popupsRef.current.set(key, popup)

      if (isSelected) {
        popup.setLngLat([lng, lat]).addTo(map)
      }
    }

    for (const p of places) {
      setup(
        `p:${p.id}`,
        p.lng,
        p.lat,
        'place',
        selectedId === p.id,
        p.category === 'hotel' ? p.hotel_legal_status : null,
        buildPlacePopup(p),
        () => onMarkerClick(p.id, 'place'),
      )
    }

    for (const r of recommendations) {
      setup(
        `r:${r.attraction.id}`,
        r.attraction.lng,
        r.attraction.lat,
        'recommendation',
        selectedId === r.attraction.id,
        null,
        buildRecPopup(r),
        () => onMarkerClick(r.attraction.id, 'recommendation'),
      )
    }

    for (const [key, marker] of markersRef.current) {
      if (!want.has(key)) {
        marker.remove()
        markersRef.current.delete(key)
        popupsRef.current.get(key)?.remove()
        popupsRef.current.delete(key)
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
