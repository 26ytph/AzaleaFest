'use client'

import dynamic from 'next/dynamic'
import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { useTranslations } from 'next-intl'
import ItineraryTimeline from '@/components/ItineraryTimeline'
import AIChatPanel from '@/components/AIChatPanel'
import { useTrip } from '@/hooks/useTrips'
import { usePlaces } from '@/hooks/usePlaces'
import { api, getSessionId } from '@/lib/api'
import { tripsStore } from '@/lib/trips'
import { mockRecommendations } from '@/lib/mock'
import type { Itinerary } from '@/lib/types'
import type { EnrichedStop } from '@/components/TripMap'

const TripMap = dynamic(() => import('@/components/TripMap'), {
  ssr: false,
  loading: () => (
    <div className="flex h-[420px] items-center justify-center rounded-xl border border-slate-200 bg-white text-slate-400">
      …
    </div>
  ),
})

export default function TripDetailPage() {
  const params = useParams<{ id: string }>()
  const tripId = params?.id ?? null
  const router = useRouter()
  const t = useTranslations()
  const { trip } = useTrip(tripId)

  const [sessionId, setSessionId] = useState<string | null>(null)
  const [aiBusy, setAiBusy] = useState(false)
  const [selectedPlaceId, setSelectedPlaceId] = useState<number | null>(null)

  useEffect(() => {
    setSessionId(getSessionId())
  }, [])

  const { places } = usePlaces(sessionId)

  const enrichedStops = useMemo<EnrichedStop[]>(() => {
    if (!trip?.itinerary) return []
    const placeMap = new Map(places.map((p) => [p.id, { lat: p.lat, lng: p.lng }]))
    const recMap = new Map(
      mockRecommendations.map((r) => [
        r.attraction.id,
        { lat: r.attraction.lat, lng: r.attraction.lng },
      ]),
    )
    const out: EnrichedStop[] = []
    for (const stop of trip.itinerary.stops) {
      const coords = placeMap.get(stop.place_id) ?? recMap.get(stop.place_id)
      if (coords) out.push({ ...stop, ...coords })
    }
    return out
  }, [trip?.itinerary, places])

  if (!trip) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-50">
        <div className="rounded-xl border border-slate-200 bg-white p-8 text-center shadow-sm">
          <p className="text-sm text-slate-600">{t('tripDetail.notFound')}</p>
          <Link href="/" className="mt-4 inline-block text-sm text-blue-600 hover:underline">
            {t('tripDetail.backHome')}
          </Link>
        </div>
      </main>
    )
  }

  const updateItinerary = (next: Itinerary) => {
    tripsStore.setItinerary(trip.id, next)
  }

  const handleAiPrompt = async (prompt: string) => {
    if (!sessionId) return
    tripsStore.appendChat(trip.id, 'user', prompt)
    setAiBusy(true)
    try {
      const merged = {
        ...trip.preferences,
        expectation: [trip.preferences.expectation, prompt].filter(Boolean).join('\n'),
      }
      tripsStore.update(trip.id, { preferences: merged })

      const next = await api.generateItinerary(
        sessionId,
        trip.preferences.dateStart,
        trip.preferences.startTime,
      )
      tripsStore.setItinerary(trip.id, next)
      tripsStore.appendChat(
        trip.id,
        'assistant',
        t('tripDetail.chat.updatedSummary', {
          count: next.stops.length,
          hours: next.total_duration_hours,
        }),
      )
    } catch (e) {
      tripsStore.appendChat(
        trip.id,
        'assistant',
        t('tripDetail.chat.regenerateFailed', {
          message: e instanceof Error ? e.message : t('tripDetail.chat.unknownError'),
        }),
      )
    } finally {
      setAiBusy(false)
    }
  }

  return (
    <main className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white px-6 py-3">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4">
          <Link href="/" className="text-sm text-slate-500 hover:text-slate-700">
            {t('tripDetail.backToMap')}
          </Link>
          <input
            type="text"
            value={trip.title}
            onChange={(e) => tripsStore.update(trip.id, { title: e.target.value })}
            className="flex-1 max-w-md rounded border border-transparent px-2 py-1 text-center text-base font-semibold text-slate-900 hover:border-slate-200 focus:border-blue-300 focus:outline-none"
          />
          <button
            type="button"
            onClick={() => {
              if (confirm(t('tripDetail.confirmDelete'))) {
                tripsStore.remove(trip.id)
                router.push('/')
              }
            }}
            className="rounded text-sm text-rose-600 hover:bg-rose-50 px-2 py-1"
          >
            {t('common.delete')}
          </button>
        </div>
      </header>

      <div className="mx-auto grid max-w-6xl grid-cols-1 gap-4 px-4 py-6 lg:grid-cols-[2fr_1.2fr]">
        <section className="space-y-4">
          <PreferencesSummary
            trip={trip}
            placeNamesById={Object.fromEntries(places.map((p) => [p.id, p.name]))}
          />

          {trip.itinerary && (
            <TripMap
              stops={enrichedStops}
              selectedPlaceId={selectedPlaceId}
              onSelectStop={(id) =>
                setSelectedPlaceId((cur) => (cur === id ? null : id))
              }
            />
          )}

          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            {trip.itinerary ? (
              <ItineraryTimeline
                itinerary={trip.itinerary}
                editable
                onChange={updateItinerary}
                onSelectStop={(id) =>
                  setSelectedPlaceId((cur) => (cur === id ? null : id))
                }
              />
            ) : (
              <div className="py-12 text-center text-sm text-slate-500">
                {t('tripDetail.noItinerary')}
              </div>
            )}
          </div>

          {trip.itinerary && enrichedStops.length < trip.itinerary.stops.length && (
            <p className="rounded bg-amber-50 px-3 py-2 text-[11px] text-amber-800">
              {t('tripDetail.partialMapWarning', {
                visible: enrichedStops.length,
                total: trip.itinerary.stops.length,
              })}
            </p>
          )}
        </section>

        <section className="lg:sticky lg:top-4 lg:h-[calc(100vh-7rem)]">
          <AIChatPanel
            history={trip.history}
            onSend={handleAiPrompt}
            busy={aiBusy}
          />
        </section>
      </div>
    </main>
  )
}

function PreferencesSummary({
  trip,
  placeNamesById,
}: {
  trip: { preferences: import('@/lib/trip-types').TripPreferences }
  placeNamesById: Record<number, string>
}) {
  const t = useTranslations()
  const p = trip.preferences

  const transportTagKey: Record<string, string> = {
    public: 'transportPublic',
    walk: 'transportWalk',
    bike: 'transportBike',
  }
  const paceTagKey: Record<string, string> = {
    compact: 'paceCompact',
    normal: 'paceNormal',
    leisurely: 'paceLeisurely',
  }
  const themeIconLabel: Record<string, string> = {
    food: '🍜',
    nature: '🏞️',
    arts: '🎨',
    shopping: '🛍️',
    history: '🏯',
  }

  const tags: string[] = []
  if (p.luckyPick) tags.push(t('tripDetail.tags.lucky'))
  tags.push(t(`tripDetail.tags.${paceTagKey[p.pace] ?? 'paceNormal'}` as any))
  if (p.diet === 'vegetarian') tags.push(t('tripDetail.tags.vegetarian'))
  if (p.diet === 'halal') tags.push(t('tripDetail.tags.halal'))
  if (p.diet === 'other' && p.dietNote)
    tags.push(t('tripDetail.tags.dietOther', { note: p.dietNote }))
  else if (p.dietNote) tags.push(t('tripDetail.tags.dietExtra', { note: p.dietNote }))
  if (p.mobility === 'low_walking') tags.push(t('tripDetail.tags.lowWalking'))
  for (const tr of p.transport) {
    const key = transportTagKey[tr]
    if (key) tags.push(t(`tripDetail.tags.${key}` as any))
  }
  for (const th of p.themes) {
    if (th === 'custom' && p.customTheme)
      tags.push(t('tripDetail.tags.customTheme', { label: p.customTheme }))
    else if (th !== 'custom' && themeIconLabel[th])
      tags.push(`${themeIconLabel[th]} ${t(`tripWizard.themeOptions.${th}` as any).replace(/^[^\s]*\s/, '')}`)
  }

  const mustVisitNames = p.mustVisitPlaceIds
    .map((id) => placeNamesById[id])
    .filter(Boolean)
    .slice(0, 4)

  const dateValue =
    p.dateStart === p.dateEnd ? p.dateStart : `${p.dateStart} → ${p.dateEnd}`

  const districtsLabel = p.districts.length
    ? p.districts.map((d) => t(`tripWizard.districtNames.${d}` as any)).join('、')
    : t('tripDetail.summary.anyDistrict')

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
        <Stat label={t('tripDetail.summary.date')} value={dateValue} />
        <Stat label={t('tripDetail.summary.time')} value={`${p.startTime} – ${p.endTime}`} />
        <Stat
          label={t('tripDetail.summary.budget')}
          value={t('tripDetail.summary.budgetValue', { amount: p.budget.toLocaleString() })}
        />
        <Stat label={t('tripDetail.summary.districts')} value={districtsLabel} />
      </div>

      {tags.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {tags.map((tg) => (
            <span
              key={tg}
              className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600"
            >
              {tg}
            </span>
          ))}
        </div>
      )}

      {p.expectation && (
        <p className="mt-3 rounded bg-slate-50 px-3 py-2 text-xs text-slate-600">
          💬 {p.expectation}
        </p>
      )}

      {mustVisitNames.length > 0 && (
        <p className="mt-2 text-[11px] text-slate-500">
          {t('tripDetail.summary.mustVisit', { names: mustVisitNames.join('、') })}
          {p.mustVisitPlaceIds.length > mustVisitNames.length &&
            ' ' + t('tripDetail.summary.mustVisitMore', {
              count: p.mustVisitPlaceIds.length,
            })}
        </p>
      )}
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[11px] text-slate-500">{label}</div>
      <div className="text-sm font-medium text-slate-900">{value}</div>
    </div>
  )
}
