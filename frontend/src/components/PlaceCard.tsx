'use client'

import clsx from 'clsx'
import { useTranslations } from 'next-intl'
import type { Place } from '@/lib/types'
import HotelBadge from './HotelBadge'

const CATEGORY_ICON: Record<Place['category'], string> = {
  food: '🍽️',
  attraction: '🏛️',
  hotel: '🏨',
}

const CATEGORY_BORDER: Record<Place['category'], string> = {
  food: 'border-l-amber-500',
  attraction: 'border-l-emerald-500',
  hotel: 'border-l-violet-500',
}

const CATEGORY_TINT: Record<Place['category'], string> = {
  food: 'bg-amber-50/40',
  attraction: 'bg-emerald-50/40',
  hotel: 'bg-violet-50/40',
}

export interface PlaceCardProps {
  place: Place
  isSelected?: boolean
  onClick?: () => void
  onDelete?: () => void
  onAddToTrip?: () => void
}

export default function PlaceCard({
  place,
  isSelected = false,
  onClick,
  onDelete,
  onAddToTrip,
}: PlaceCardProps) {
  const t = useTranslations()
  return (
    <article
      onClick={onClick}
      className={clsx(
        'group cursor-pointer rounded-lg border border-l-4 bg-white p-3 shadow-sm transition hover:shadow-md',
        CATEGORY_BORDER[place.category],
        CATEGORY_TINT[place.category],
        isSelected
          ? 'border-slate-300 ring-2 ring-blue-200'
          : 'border-slate-200',
      )}
    >
      <header className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span aria-hidden>{CATEGORY_ICON[place.category]}</span>
            <h3 className="truncate text-sm font-semibold text-slate-900">{place.name}</h3>
          </div>
          {place.address && (
            <p className="mt-0.5 truncate text-xs text-slate-500">{place.address}</p>
          )}
        </div>
        <span className="shrink-0 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-slate-500">
          {t(`placeCard.source.${place.source_type}` as any)}
        </span>
      </header>

      {place.description && (
        <p className="mt-2 line-clamp-2 text-xs text-slate-600">{place.description}</p>
      )}

      {place.category === 'hotel' && (
        <div className="mt-2">
          <HotelBadge status={place.hotel_legal_status} />
        </div>
      )}

      {(onDelete || onAddToTrip) && (
        <footer className="mt-3 flex items-center justify-end gap-2 opacity-0 transition group-hover:opacity-100">
          {onAddToTrip && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                onAddToTrip()
              }}
              className="rounded-md border border-slate-200 px-2 py-1 text-xs text-slate-700 hover:border-blue-400 hover:text-blue-600"
            >
              {t('placeCard.addToTrip')}
            </button>
          )}
          {onDelete && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                onDelete()
              }}
              className="rounded-md border border-rose-200 px-2 py-1 text-xs text-rose-600 hover:bg-rose-50"
            >
              {t('placeCard.remove')}
            </button>
          )}
        </footer>
      )}
    </article>
  )
}
