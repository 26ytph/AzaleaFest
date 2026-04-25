'use client'

import clsx from 'clsx'
import { useLocale, useTranslations } from 'next-intl'
import type { RecommendResult } from '@/lib/types'
import type { Locale } from '@/i18n/config'
import { pickName } from '@/lib/i18n'

const CATEGORY_ICON: Record<string, string> = {
  food: '🍽️',
  attraction: '🏛️',
  hotel: '🏨',
}

export interface RecommendCardProps {
  rec: RecommendResult
  isSelected?: boolean
  onClick?: () => void
  onAdd?: () => void
}

export default function RecommendCard({
  rec,
  isSelected = false,
  onClick,
  onAdd,
}: RecommendCardProps) {
  const t = useTranslations()
  const locale = useLocale() as Locale
  const { attraction, reason, score } = rec
  const displayName = pickName(attraction, locale)
  return (
    <article
      onClick={onClick}
      className={clsx(
        'group cursor-pointer rounded-lg border bg-white p-3 shadow-sm transition hover:border-amber-400',
        isSelected ? 'border-l-4 border-l-amber-500 ring-1 ring-amber-100' : 'border-slate-200',
      )}
    >
      <header className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span aria-hidden>{CATEGORY_ICON[attraction.category] ?? '📍'}</span>
            <h3 className="truncate text-sm font-semibold text-slate-900">{displayName}</h3>
          </div>
          {attraction.address && (
            <p className="mt-0.5 truncate text-xs text-slate-500">{attraction.address}</p>
          )}
        </div>
        <span className="shrink-0 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">
          {t('recommendCard.similarity', { score: (1 - score).toFixed(2) })}
        </span>
      </header>

      <p className="mt-2 text-xs italic text-amber-700">「{reason}」</p>

      {attraction.tags?.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {attraction.tags.slice(0, 4).map((tag) => (
            <span
              key={tag}
              className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-600"
            >
              #{tag}
            </span>
          ))}
        </div>
      )}

      {onAdd && (
        <footer className="mt-3 flex items-center justify-end opacity-0 transition group-hover:opacity-100">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              onAdd()
            }}
            className="rounded-md border border-blue-200 px-2 py-1 text-xs text-blue-600 hover:bg-blue-50"
          >
            {t('recommendCard.addToFavorites')}
          </button>
        </footer>
      )}
    </article>
  )
}
