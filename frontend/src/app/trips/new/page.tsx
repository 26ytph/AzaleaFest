'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useTranslations } from 'next-intl'
import TripWizard from '@/components/TripWizard'
import { usePlaces } from '@/hooks/usePlaces'
import { api, getSessionId } from '@/lib/api'
import { tripsStore } from '@/lib/trips'
import type { TripPreferences } from '@/lib/trip-types'

export default function NewTripPage() {
  const router = useRouter()
  const t = useTranslations()
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setSessionId(getSessionId())
  }, [])

  const { places } = usePlaces(sessionId)

  const handleSubmit = async (title: string, prefs: TripPreferences) => {
    if (!sessionId) return
    setSubmitting(true)
    setError(null)

    const trip = tripsStore.create({ title, preferences: prefs })

    try {
      const itinerary = await api.generateItinerary(sessionId, prefs.dateStart, prefs.startTime)
      tripsStore.setItinerary(trip.id, itinerary)
      tripsStore.appendChat(
        trip.id,
        'assistant',
        t('newTrip.successMessage', {
          count: itinerary.stops.length,
          hours: itinerary.total_duration_hours,
        }),
      )
      router.push(`/trips/${trip.id}`)
    } catch (e) {
      setError(e instanceof Error ? e.message : t('newTrip.genericFailure'))
      setSubmitting(false)
    }
  }

  return (
    <main className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white px-6 py-3">
        <div className="mx-auto flex max-w-3xl items-center justify-between">
          <Link href="/" className="text-sm text-slate-500 hover:text-slate-700">
            {t('newTrip.backToMap')}
          </Link>
          <h1 className="text-sm font-semibold text-slate-900">{t('newTrip.header')}</h1>
          <span className="w-16" />
        </div>
      </header>

      <div className="mx-auto max-w-3xl px-4 py-6">
        {error && (
          <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-2 text-sm text-rose-700">
            {error}
          </div>
        )}

        {submitting ? (
          <div className="flex flex-col items-center gap-3 rounded-xl border border-slate-200 bg-white p-12">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
            <p className="text-sm text-slate-600">{t('newTrip.loading')}</p>
          </div>
        ) : (
          <TripWizard
            places={places}
            onSubmit={handleSubmit}
            onCancel={() => router.push('/')}
          />
        )}
      </div>
    </main>
  )
}
