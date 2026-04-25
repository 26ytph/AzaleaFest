'use client'

import { useEffect, useRef } from 'react'
import mapboxgl from 'mapbox-gl'
import 'mapbox-gl/dist/mapbox-gl.css'
import { useTranslations } from 'next-intl'
import type { ItineraryStop } from '@/lib/types'

export type EnrichedStop = ItineraryStop & {
  lat: number
  lng: number
}

export interface TripMapProps {
  stops: EnrichedStop[]
  selectedPlaceId: number | null
  onSelectStop?: (placeId: number) => void
  height?: string
}

const TAIPEI_CENTER: [number, number] = [121.5654, 25.033]
const TOKEN = process.env.NEXT_PUBLIC_MAPBOX_TOKEN
const ROUTE_SOURCE = 'wg-trip-route'
const ROUTE_LAYER = 'wg-trip-route-line'

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

export default function TripMap({
  stops,
  selectedPlaceId,
  onSelectStop,
  height = '420px',
}: TripMapProps) {
  const t = useTranslations()
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<mapboxgl.Map | null>(null)
  const markersRef = useRef<mapboxgl.Marker[]>([])
  const popupsRef = useRef<mapboxgl.Popup[]>([])
  const initialFitRef = useRef(false)

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
    return () => {
      ref.current?.remove()
      ref.current = null
      markersRef.current = []
      popupsRef.current = []
    }
  }, [])

  // sync stops, route, markers
  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    const apply = () => {
      // clear old markers / popups
      markersRef.current.forEach((m) => m.remove())
      popupsRef.current.forEach((p) => p.remove())
      markersRef.current = []
      popupsRef.current = []

      // route line as GeoJSON
      const data: GeoJSON.Feature<GeoJSON.LineString> = {
        type: 'Feature',
        properties: {},
        geometry: {
          type: 'LineString',
          coordinates: stops.map((s) => [s.lng, s.lat]),
        },
      }
      const existing = map.getSource(ROUTE_SOURCE) as mapboxgl.GeoJSONSource | undefined
      if (existing) {
        existing.setData(data)
      } else {
        map.addSource(ROUTE_SOURCE, { type: 'geojson', data })
        map.addLayer({
          id: ROUTE_LAYER,
          type: 'line',
          source: ROUTE_SOURCE,
          layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: {
            'line-color': '#3B82F6',
            'line-width': 3,
            'line-dasharray': [1, 1.5],
            'line-opacity': 0.65,
          },
        })
      }

      // numbered markers
      stops.forEach((stop, idx) => {
        const el = document.createElement('div')
        el.className = 'wg-trip-marker'
        el.dataset.selected = String(selectedPlaceId === stop.place_id)
        el.textContent = String(idx + 1)

        const popupHtml =
          '<div class="wg-pop">' +
          `<div class="wg-pop-title">${idx + 1}. ${escapeHtml(stop.name)}</div>` +
          `<div class="wg-pop-cat">🕒 ${escapeHtml(stop.time)} · ${escapeHtml(t('tripMap.stayMinutes', { minutes: stop.duration_min }))}</div>` +
          (stop.transport_to_next
            ? `<div class="wg-pop-desc">→ ${escapeHtml(stop.transport_to_next)}</div>`
            : '') +
          (stop.note ? `<div class="wg-pop-desc">${escapeHtml(stop.note)}</div>` : '') +
          '</div>'

        const popup = new mapboxgl.Popup({
          offset: 18,
          closeButton: false,
          closeOnClick: false,
          className: 'wg-popup',
        }).setHTML(popupHtml)

        el.addEventListener('mouseenter', () => {
          popup.setLngLat([stop.lng, stop.lat]).addTo(map)
        })
        el.addEventListener('mouseleave', () => {
          if (selectedPlaceId !== stop.place_id) popup.remove()
        })
        el.addEventListener('click', (e) => {
          e.stopPropagation()
          popup.setLngLat([stop.lng, stop.lat]).addTo(map)
          onSelectStop?.(stop.place_id)
        })

        const marker = new mapboxgl.Marker({ element: el })
          .setLngLat([stop.lng, stop.lat])
          .addTo(map)
        markersRef.current.push(marker)
        popupsRef.current.push(popup)

        if (selectedPlaceId === stop.place_id) {
          popup.setLngLat([stop.lng, stop.lat]).addTo(map)
        }
      })

      // fit bounds on first non-empty render
      if (stops.length > 0 && !initialFitRef.current) {
        const bounds = new mapboxgl.LngLatBounds()
        stops.forEach((s) => bounds.extend([s.lng, s.lat]))
        if (!bounds.isEmpty()) {
          map.fitBounds(bounds, { padding: 60, maxZoom: 14, duration: 0 })
          initialFitRef.current = true
        }
      }
    }

    if (map.isStyleLoaded()) apply()
    else map.once('load', apply)
  }, [stops, selectedPlaceId, onSelectStop, t])

  // flyTo on select
  useEffect(() => {
    if (!mapRef.current || selectedPlaceId == null) return
    const target = stops.find((s) => s.place_id === selectedPlaceId)
    if (!target) return
    mapRef.current.flyTo({
      center: [target.lng, target.lat],
      zoom: 15,
      speed: 1.2,
    })
  }, [selectedPlaceId, stops])

  return (
    <div
      className="relative w-full overflow-hidden rounded-xl border border-slate-200"
      style={{ height }}
    >
      <div ref={containerRef} className="absolute inset-0 h-full" />
      {!TOKEN && (
        <div className="absolute left-3 top-3 rounded bg-amber-100 px-3 py-2 text-xs text-amber-800 shadow">
          {t('home.missingMapboxToken')}
        </div>
      )}
      {stops.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center bg-white/70 text-sm text-slate-500">
          {t('tripMap.noStops')}
        </div>
      )}
    </div>
  )
}
