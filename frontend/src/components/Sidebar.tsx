'use client'

import { useState } from 'react'
import clsx from 'clsx'
import Link from 'next/link'
import { useTranslations } from 'next-intl'
import type { Place, RecommendResult } from '@/lib/types'
import type { TripPlan } from '@/lib/trip-types'
import LanguageSwitcher from './LanguageSwitcher'
import PlaceCard from './PlaceCard'
import RecommendCard from './RecommendCard'

export type SidebarTab = 'places' | 'recommend' | 'trips'
export type CategoryFilter = 'all' | 'food' | 'attraction' | 'hotel'

const CATEGORY_FILTERS: { id: CategoryFilter; labelKey: string }[] = [
  { id: 'all', labelKey: 'all' },
  { id: 'food', labelKey: 'foodWithIcon' },
  { id: 'attraction', labelKey: 'attractionWithIcon' },
  { id: 'hotel', labelKey: 'hotelWithIcon' },
]

export interface SidebarProps {
  places: Place[]
  recommendations: RecommendResult[]
  trips: TripPlan[]
  selectedId: number | null
  category: CategoryFilter
  onCategoryChange: (c: CategoryFilter) => void
  onSelectPlace: (id: number) => void
  onDeletePlace: (id: number) => void
  onAddRecommendation: (rec: RecommendResult) => void
  onCreateTrip: () => void
  onAddPlaceToTrip: (placeId: number) => void
  onDeleteTrip: (tripId: string) => void
}

export default function Sidebar(props: SidebarProps) {
  const t = useTranslations()
  const [tab, setTab] = useState<SidebarTab>('places')

  const tabItems: { id: SidebarTab; label: string }[] = [
    { id: 'places', label: t('sidebar.tabs.places') },
    { id: 'recommend', label: t('sidebar.tabs.recommend') },
    { id: 'trips', label: t('sidebar.tabs.trips') },
  ]

  return (
    <aside className="flex h-full w-[380px] shrink-0 flex-col border-r border-slate-200 bg-white">
      <header className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <h1 className="text-base font-semibold text-slate-900">{t('brand')}</h1>
        <div className="flex items-center gap-2">
          <span className="rounded bg-slate-100 px-2 py-0.5 text-[10px] text-slate-500">
            {t('sidebar.placesCount', { count: props.places.length })}
          </span>
          <LanguageSwitcher />
        </div>
      </header>

      <nav className="flex border-b border-slate-200 text-sm">
        {tabItems.map((tItem) => (
          <button
            key={tItem.id}
            type="button"
            onClick={() => setTab(tItem.id)}
            className={clsx(
              'flex-1 border-b-2 py-2 transition',
              tab === tItem.id
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-slate-500 hover:text-slate-700',
            )}
          >
            {tItem.label}
          </button>
        ))}
      </nav>

      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {tab === 'places' && <PlacesPanel {...props} />}
        {tab === 'recommend' && <RecommendPanel {...props} />}
        {tab === 'trips' && <TripsPanel {...props} />}
      </div>

      {tab === 'places' && (
        <footer className="border-t border-slate-200 p-3">
          <button
            type="button"
            onClick={props.onCreateTrip}
            disabled={props.places.length === 0}
            className="w-full rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-slate-300"
          >
            {t('sidebar.generateButton')}
          </button>
        </footer>
      )}
    </aside>
  )
}

function PlacesPanel({
  places,
  selectedId,
  category,
  onCategoryChange,
  onSelectPlace,
  onDeletePlace,
}: SidebarProps) {
  const t = useTranslations()

  if (places.length === 0) {
    return (
      <EmptyState
        title={t('sidebar.places.emptyTitle')}
        body={
          <>
            {t('sidebar.places.emptyBody1')}
            <br />
            {t('sidebar.places.emptyBody2')}
          </>
        }
      />
    )
  }

  const filtered =
    category === 'all'
      ? places
      : places.filter((p) => p.category === category)

  const counts: Record<CategoryFilter, number> = {
    all: places.length,
    food: places.filter((p) => p.category === 'food').length,
    attraction: places.filter((p) => p.category === 'attraction').length,
    hotel: places.filter((p) => p.category === 'hotel').length,
  }

  return (
    <div className="space-y-3 p-3">
      <div className="flex flex-wrap gap-1.5">
        {CATEGORY_FILTERS.map((f) => (
          <button
            key={f.id}
            type="button"
            onClick={() => onCategoryChange(f.id)}
            className={clsx(
              'rounded-full border px-2.5 py-1 text-xs transition',
              category === f.id
                ? f.id === 'food'
                  ? 'border-amber-400 bg-amber-50 text-amber-700'
                  : f.id === 'attraction'
                  ? 'border-emerald-400 bg-emerald-50 text-emerald-700'
                  : f.id === 'hotel'
                  ? 'border-violet-400 bg-violet-50 text-violet-700'
                  : 'border-slate-400 bg-slate-100 text-slate-700'
                : 'border-slate-200 text-slate-600 hover:border-slate-300',
            )}
          >
            {t(`category.${f.labelKey}` as any)}
            <span className="ml-1 text-[10px] text-slate-400">{counts[f.id]}</span>
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <p className="rounded bg-slate-50 px-3 py-2 text-xs text-slate-500">
          {t('sidebar.places.filterEmpty')}
        </p>
      ) : (
        <ul className="space-y-2">
          {filtered.map((place) => (
            <li key={place.id}>
              <PlaceCard
                place={place}
                isSelected={selectedId === place.id}
                onClick={() => onSelectPlace(place.id)}
                onDelete={() => onDeletePlace(place.id)}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function RecommendPanel({
  recommendations,
  selectedId,
  category,
  onCategoryChange,
  onSelectPlace,
  onAddRecommendation,
  places,
}: SidebarProps) {
  const t = useTranslations()

  return (
    <div className="space-y-3 p-3">
      <div className="flex flex-wrap gap-1.5">
        {CATEGORY_FILTERS.map((f) => (
          <button
            key={f.id}
            type="button"
            onClick={() => onCategoryChange(f.id)}
            className={clsx(
              'rounded-full border px-2.5 py-1 text-xs transition',
              category === f.id
                ? 'border-amber-400 bg-amber-50 text-amber-700'
                : 'border-slate-200 text-slate-600 hover:border-slate-300',
            )}
          >
            {t(`category.${f.labelKey}` as any)}
          </button>
        ))}
      </div>

      {places.length === 0 && (
        <p className="rounded bg-slate-50 px-3 py-2 text-xs text-slate-500">
          {t('sidebar.recommend.needPlaces')}
        </p>
      )}

      {recommendations.length === 0 && places.length > 0 && (
        <p className="rounded bg-slate-50 px-3 py-2 text-xs text-slate-500">
          {t('sidebar.recommend.filterEmpty')}
        </p>
      )}

      <ul className="space-y-2">
        {recommendations.map((rec) => (
          <li key={rec.attraction.id}>
            <RecommendCard
              rec={rec}
              isSelected={selectedId === rec.attraction.id}
              onClick={() => onSelectPlace(rec.attraction.id)}
              onAdd={() => onAddRecommendation(rec)}
            />
          </li>
        ))}
      </ul>
    </div>
  )
}

function TripsPanel({
  trips,
  onCreateTrip,
  onDeleteTrip,
}: SidebarProps) {
  const t = useTranslations()

  return (
    <div className="space-y-3 p-3">
      <button
        type="button"
        onClick={onCreateTrip}
        className="flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-blue-300 py-2 text-sm text-blue-600 transition hover:bg-blue-50"
      >
        {t('sidebar.trips.create')}
      </button>

      {trips.length === 0 ? (
        <EmptyState
          title={t('sidebar.trips.emptyTitle')}
          body={t('sidebar.trips.emptyBody')}
        />
      ) : (
        <ul className="space-y-2">
          {trips.map((trip) => (
            <li
              key={trip.id}
              className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm transition hover:border-blue-300"
            >
              <Link href={`/trips/${trip.id}`} className="block">
                <div className="flex items-center justify-between gap-2">
                  <h3 className="truncate text-sm font-semibold text-slate-900">
                    {trip.title}
                  </h3>
                  <span className="shrink-0 text-[11px] text-slate-500">
                    {trip.preferences.dateStart === trip.preferences.dateEnd
                      ? trip.preferences.dateStart
                      : `${trip.preferences.dateStart}–${trip.preferences.dateEnd.slice(5)}`}
                  </span>
                </div>
                <p className="mt-1 text-xs text-slate-500">
                  {trip.itinerary
                    ? t('sidebar.trips.stopsAndHours', {
                        count: trip.itinerary.stops.length,
                        hours: trip.itinerary.total_duration_hours,
                      })
                    : t('sidebar.trips.noItinerary')}
                </p>
              </Link>
              <div className="mt-2 flex justify-end">
                <button
                  type="button"
                  onClick={() => onDeleteTrip(trip.id)}
                  className="rounded px-2 py-0.5 text-[11px] text-rose-600 hover:bg-rose-50"
                >
                  {t('common.delete')}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function EmptyState({
  title,
  body,
}: {
  title: string
  body: React.ReactNode
}) {
  return (
    <div className="px-6 py-12 text-center text-slate-500">
      <p className="text-sm font-medium text-slate-700">{title}</p>
      <p className="mt-2 text-xs leading-relaxed">{body}</p>
    </div>
  )
}
