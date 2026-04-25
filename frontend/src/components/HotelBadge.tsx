import clsx from 'clsx'

type Status = 'legal' | 'illegal' | 'unknown' | null | undefined

const STYLE: Record<NonNullable<Status>, { cls: string; label: string; tip: string }> = {
  legal: {
    cls: 'bg-emerald-100 text-emerald-700 border-emerald-200',
    label: '🛡️ 合法旅宿',
    tip: '已比對到合法旅館登記',
  },
  illegal: {
    cls: 'bg-rose-100 text-rose-700 border-rose-200',
    label: '⚠️ 疑似非法日租',
    tip: '可能有消防安全疑慮，建議選擇合法旅館',
  },
  unknown: {
    cls: 'bg-slate-100 text-slate-600 border-slate-200',
    label: '❓ 待確認',
    tip: '尚未完成比對',
  },
}

export default function HotelBadge({ status }: { status: Status }) {
  if (!status) return null
  const s = STYLE[status]
  return (
    <span
      className={clsx(
        'inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium',
        s.cls,
      )}
      title={s.tip}
    >
      {s.label}
    </span>
  )
}
