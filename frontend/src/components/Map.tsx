'use client'

import { useEffect, useRef } from 'react'
import mapboxgl from 'mapbox-gl'
import 'mapbox-gl/dist/mapbox-gl.css'
import { useLocale, useTranslations } from 'next-intl'
import type { Locale } from '@/i18n/config'
import type { Place, RecommendResult } from '@/lib/types'
import { pickName } from '@/lib/i18n'

export interface MapProps {
  places: Place[]
  recommendations: RecommendResult[]
  selectedId: number | null
  onMarkerClick: (id: number, type: 'place' | 'recommendation') => void
}

const TAIPEI_CENTER: [number, number] = [121.5654, 25.033]
const TOKEN = process.env.NEXT_PUBLIC_MAPBOX_TOKEN

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

function buildPlacePopup(
  p: Place,
  categoryLabel: string,
  hotelBadgeLabel: string | null,
): string {
  const parts: string[] = []
  parts.push(`<div class="wg-pop-title">${escapeHtml(p.name)}</div>`)
  parts.push(`<div class="wg-pop-cat">${escapeHtml(categoryLabel)}</div>`)
  if (p.address) parts.push(`<div class="wg-pop-addr">${escapeHtml(p.address)}</div>`)
  if (p.description) parts.push(`<div class="wg-pop-desc">${escapeHtml(p.description)}</div>`)
  if (p.category === 'hotel' && p.hotel_legal_status && hotelBadgeLabel) {
    parts.push(`<div class="wg-pop-hotel ${p.hotel_legal_status}">${escapeHtml(hotelBadgeLabel)}</div>`)
  }
  return `<div class="wg-pop">${parts.join('')}</div>`
}

function buildRecPopup(
  r: RecommendResult,
  displayName: string,
  categoryLabel: string,
): string {
  const a = r.attraction
  const parts: string[] = []
  parts.push(`<div class="wg-pop-title">${escapeHtml(displayName)}</div>`)
  parts.push(`<div class="wg-pop-cat">${escapeHtml(categoryLabel)}</div>`)
  if (a.address) parts.push(`<div class="wg-pop-addr">${escapeHtml(a.address)}</div>`)
  if (r.reason) parts.push(`<div class="wg-pop-reason">「${escapeHtml(r.reason)}」</div>`)
  if (a.tags?.length) {
    parts.push(
      `<div class="wg-pop-tags">${a.tags
        .slice(0, 5)
        .map((tag) => `<span>#${escapeHtml(tag)}</span>`)
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
  const t = useTranslations()
  const locale = useLocale() as Locale
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<mapboxgl.Map | null>(null)
  const markersRef = useRef<globalThis.Map<string, mapboxgl.Marker>>(new globalThis.Map())
  const popupsRef = useRef<globalThis.Map<string, mapboxgl.Popup>>(new globalThis.Map())

  const categoryLabel = (cat: string): string => {
    if (cat === 'food') return t('category.foodWithIcon')
    if (cat === 'attraction') return t('category.attractionWithIcon')
    if (cat === 'hotel') return t('category.hotelWithIcon')
    return ''
  }
  const hotelBadgeLabel = (status: 'legal' | 'illegal' | 'unknown'): string =>
    t(`hotelBadge.${status}.label` as any)

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
      const legalStatus = p.category === 'hotel' ? p.hotel_legal_status : null
      const badgeLabel = legalStatus ? hotelBadgeLabel(legalStatus) : null
      setup(
        `p:${p.id}`,
        p.lng,
        p.lat,
        'place',
        selectedId === p.id,
        legalStatus,
        buildPlacePopup(p, categoryLabel(p.category), badgeLabel),
        () => onMarkerClick(p.id, 'place'),
      )
    }

    for (const r of recommendations) {
      const displayName = pickName(r.attraction, locale)
      setup(
        `r:${r.attraction.id}`,
        r.attraction.lng,
        r.attraction.lat,
        'recommendation',
        selectedId === r.attraction.id,
        null,
        buildRecPopup(r, displayName, categoryLabel(r.attraction.category)),
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
  }, [places, recommendations, selectedId, onMarkerClick, locale, t])

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
          {t('home.missingMapboxToken')}
        </div>
      )}
    </div>
  )
}
