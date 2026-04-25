'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import ItineraryTimeline from '@/components/ItineraryTimeline'
import AIChatPanel from '@/components/AIChatPanel'
import { useTrip } from '@/hooks/useTrips'
import { usePlaces } from '@/hooks/usePlaces'
import { api, getSessionId } from '@/lib/api'
import { tripsStore } from '@/lib/trips'
import type { Itinerary } from '@/lib/types'

export default function TripDetailPage() {
  const params = useParams<{ id: string }>()
  const tripId = params?.id ?? null
  const router = useRouter()
  const { trip } = useTrip(tripId)

  const [sessionId, setSessionId] = useState<string | null>(null)
  const [aiBusy, setAiBusy] = useState(false)

  useEffect(() => {
    setSessionId(getSessionId())
  }, [])

  const { places } = usePlaces(sessionId)

  if (!trip) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-50">
        <div className="rounded-xl border border-slate-200 bg-white p-8 text-center shadow-sm">
          <p className="text-sm text-slate-600">找不到這個行程，可能已被刪除。</p>
          <Link href="/" className="mt-4 inline-block text-sm text-blue-600 hover:underline">
            回到地圖
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
      // Spec only defines POST /itinerary/generate; we re-call it as the
      // refinement endpoint and let the backend interpret the user prompt
      // by including it in trip preferences.expectation. This stays within
      // the spec's HTTP contract.
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
        `已更新行程：${next.stops.length} 站、約 ${next.total_duration_hours} 小時。`,
      )
    } catch (e) {
      tripsStore.appendChat(
        trip.id,
        'assistant',
        `重新生成失敗：${e instanceof Error ? e.message : '未知錯誤'}`,
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
            ← 回到地圖
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
              if (confirm('確定要刪除此行程？')) {
                tripsStore.remove(trip.id)
                router.push('/')
              }
            }}
            className="rounded text-sm text-rose-600 hover:bg-rose-50 px-2 py-1"
          >
            刪除
          </button>
        </div>
      </header>

      <div className="mx-auto grid max-w-6xl grid-cols-1 gap-4 px-4 py-6 lg:grid-cols-[2fr_1.2fr]">
        <section className="space-y-4">
          <PreferencesSummary
            trip={trip}
            placeNamesById={Object.fromEntries(places.map((p) => [p.id, p.name]))}
          />

          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            {trip.itinerary ? (
              <ItineraryTimeline
                itinerary={trip.itinerary}
                editable
                onChange={updateItinerary}
              />
            ) : (
              <div className="py-12 text-center text-sm text-slate-500">
                尚未生成行程內容。
              </div>
            )}
          </div>
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
  const p = trip.preferences

  const transportLabel: Record<string, string> = {
    public: '🚇 大眾運輸',
    walk: '🚶 步行',
    bike: '🚲 自行車',
  }
  const paceLabel: Record<string, string> = {
    compact: '緊湊節奏',
    normal: '一般節奏',
    leisurely: '愜意節奏',
  }

  const tags: string[] = []
  if (p.luckyPick) tags.push('🎲 好手氣')
  tags.push(paceLabel[p.pace] ?? '一般節奏')
  if (p.diet === 'vegetarian') tags.push('素食')
  if (p.diet === 'halal') tags.push('清真')
  if (p.diet === 'other' && p.dietNote) tags.push(`飲食：${p.dietNote}`)
  else if (p.dietNote) tags.push(`飲食補充：${p.dietNote}`)
  if (p.mobility === 'low_walking') tags.push('少走路')
  for (const t of p.transport) {
    if (transportLabel[t]) tags.push(transportLabel[t])
  }
  for (const t of p.themes) {
    if (t === 'custom' && p.customTheme) tags.push(`✏️ ${p.customTheme}`)
    else if (t !== 'custom') tags.push(t)
  }

  const mustVisitNames = p.mustVisitPlaceIds
    .map((id) => placeNamesById[id])
    .filter(Boolean)
    .slice(0, 4)

  const dateValue =
    p.dateStart === p.dateEnd ? p.dateStart : `${p.dateStart} → ${p.dateEnd}`

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
        <Stat label="日期" value={dateValue} />
        <Stat label="時段" value={`${p.startTime} – ${p.endTime}`} />
        <Stat label="預算" value={`NT$ ${p.budget.toLocaleString()} / 日`} />
        <Stat
          label="行政區"
          value={p.districts.length ? p.districts.join('、') : '不限'}
        />
      </div>

      {tags.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {tags.map((t) => (
            <span
              key={t}
              className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600"
            >
              {t}
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
          必去：{mustVisitNames.join('、')}
          {p.mustVisitPlaceIds.length > mustVisitNames.length &&
            ` 等 ${p.mustVisitPlaceIds.length} 個`}
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
