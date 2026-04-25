'use client'

import clsx from 'clsx'
import { useTranslations } from 'next-intl'

type Status = 'legal' | 'illegal' | 'unknown' | null | undefined

const STYLE: Record<NonNullable<Status>, string> = {
  legal: 'bg-emerald-100 text-emerald-700 border-emerald-200',
  illegal: 'bg-rose-100 text-rose-700 border-rose-200',
  unknown: 'bg-slate-100 text-slate-600 border-slate-200',
}

export default function HotelBadge({ status }: { status: Status }) {
  const t = useTranslations('hotelBadge')
  if (!status) return null
  return (
    <span
      className={clsx(
        'inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium',
        STYLE[status],
      )}
      title={t(`${status}.tip` as any)}
    >
      {t(`${status}.label` as any)}
    </span>
  )
}
