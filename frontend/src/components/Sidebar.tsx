'use client'

import { useState } from 'react'
import clsx from 'clsx'
import Link from 'next/link'
import type { Place, RecommendResult } from '@/lib/types'
import type { TripPlan } from '@/lib/trip-types'
import PlaceCard from './PlaceCard'
import RecommendCard from './RecommendCard'

export type SidebarTab = 'places' | 'recommend' | 'trips'
export type CategoryFilter = 'all' | 'food' | 'attraction' | 'hotel'

const CATEGORY_FILTERS: { id: CategoryFilter; label: string }[] = [
  { id: 'all', label: '全部' },
  { id: 'food', label: '🍽️ 美食' },
  { id: 'attraction', label: '🏛️ 景點' },
  { id: 'hotel', label: '🏨 住宿' },
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
  const [tab, setTab] = useState<SidebarTab>('places')

  return (
    <aside className="flex h-full w-[380px] shrink-0 flex-col border-r border-slate-200 bg-white">
      <header className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <h1 className="text-base font-semibold text-slate-900">Taipei WanderGuard</h1>
        <span className="rounded bg-slate-100 px-2 py-0.5 text-[10px] text-slate-500">
          {props.places.length} 個收藏
        </span>
      </header>

      <nav className="flex border-b border-slate-200 text-sm">
        {(
          [
            { id: 'places', label: '收藏' },
            { id: 'recommend', label: '推薦' },
            { id: 'trips', label: '行程' },
          ] as { id: SidebarTab; label: string }[]
        ).map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={clsx(
              'flex-1 border-b-2 py-2 transition',
              tab === t.id
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-slate-500 hover:text-slate-700',
            )}
          >
            {t.label}
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
            ✨ 一鍵生成行程
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
  if (places.length === 0) {
    return (
      <EmptyState
        title="還沒有收藏的地點"
        body={
          <>
            把 IG Reels / Threads 連結傳到 Line 官方帳號，
            <br />
            或直接傳地點名稱，景點會自動出現在這裡。
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
            {f.label}
            <span className="ml-1 text-[10px] text-slate-400">{counts[f.id]}</span>
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <p className="rounded bg-slate-50 px-3 py-2 text-xs text-slate-500">
          這個分類目前沒有收藏。
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
            {f.label}
          </button>
        ))}
      </div>

      {places.length === 0 && (
        <p className="rounded bg-slate-50 px-3 py-2 text-xs text-slate-500">
          先收藏 1 個以上地點，AI 才能根據你的喜好推薦。
        </p>
      )}

      {recommendations.length === 0 && places.length > 0 && (
        <p className="rounded bg-slate-50 px-3 py-2 text-xs text-slate-500">這個分類目前沒有推薦結果。</p>
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
  return (
    <div className="space-y-3 p-3">
      <button
        type="button"
        onClick={onCreateTrip}
        className="flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-blue-300 py-2 text-sm text-blue-600 transition hover:bg-blue-50"
      >
        ＋ 建立新行程
      </button>

      {trips.length === 0 ? (
        <EmptyState
          title="還沒有行程"
          body="點上方按鈕，依日期、預算、偏好生成第一份行程。"
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
                    ? `${trip.itinerary.stops.length} 站 · 約 ${trip.itinerary.total_duration_hours} 小時`
                    : '尚未生成行程內容'}
                </p>
              </Link>
              <div className="mt-2 flex justify-end">
                <button
                  type="button"
                  onClick={() => onDeleteTrip(trip.id)}
                  className="rounded px-2 py-0.5 text-[11px] text-rose-600 hover:bg-rose-50"
                >
                  刪除
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
