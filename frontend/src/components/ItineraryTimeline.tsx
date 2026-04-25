'use client'

import type { Itinerary, ItineraryStop } from '@/lib/types'

export interface ItineraryTimelineProps {
  itinerary: Itinerary
  editable?: boolean
  onChange?: (next: Itinerary) => void
  onSelectStop?: (placeId: number) => void
}

export default function ItineraryTimeline({
  itinerary,
  editable = false,
  onChange,
  onSelectStop,
}: ItineraryTimelineProps) {
  const updateStop = (idx: number, patch: Partial<ItineraryStop>) => {
    if (!onChange) return
    const stops = itinerary.stops.map((s, i) => (i === idx ? { ...s, ...patch } : s))
    onChange({ ...itinerary, stops })
  }

  const removeStop = (idx: number) => {
    if (!onChange) return
    const stops = itinerary.stops.filter((_, i) => i !== idx)
    onChange({ ...itinerary, stops })
  }

  const moveStop = (idx: number, dir: -1 | 1) => {
    if (!onChange) return
    const target = idx + dir
    if (target < 0 || target >= itinerary.stops.length) return
    const stops = [...itinerary.stops]
    ;[stops[idx], stops[target]] = [stops[target], stops[idx]]
    onChange({ ...itinerary, stops })
  }

  return (
    <div className="space-y-1">
      <header className="flex items-center justify-between border-b border-slate-200 pb-2">
        <h2 className="text-sm font-semibold text-slate-700">行程時間軸</h2>
        <span className="text-xs text-slate-500">
          約 {itinerary.total_duration_hours} 小時 · {itinerary.stops.length} 站
        </span>
      </header>

      <ol className="relative space-y-3 pl-5 pt-3 before:absolute before:left-2 before:top-3 before:h-[calc(100%-1.5rem)] before:w-0.5 before:bg-slate-200">
        {itinerary.stops.map((stop, idx) => (
          <li key={`${stop.place_id}-${idx}`} className="relative">
            <span className="absolute -left-[18px] top-1 inline-block h-4 w-4 rounded-full border-2 border-white bg-blue-500 shadow" />
            <div
              className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm hover:border-blue-300"
              onClick={() => onSelectStop?.(stop.place_id)}
            >
              <div className="flex items-center justify-between gap-2">
                {editable ? (
                  <input
                    type="time"
                    value={stop.time}
                    onChange={(e) => updateStop(idx, { time: e.target.value })}
                    className="w-24 rounded border border-slate-200 px-1 py-0.5 text-sm font-semibold tabular-nums text-blue-600"
                    onClick={(e) => e.stopPropagation()}
                  />
                ) : (
                  <span className="text-sm font-semibold tabular-nums text-blue-600">
                    {stop.time}
                  </span>
                )}
                <span className="text-xs text-slate-500">停留 {stop.duration_min} 分</span>
              </div>

              {editable ? (
                <input
                  type="text"
                  value={stop.name}
                  onChange={(e) => updateStop(idx, { name: e.target.value })}
                  className="mt-1 w-full rounded border border-slate-200 px-1 py-0.5 text-sm font-medium text-slate-900"
                  onClick={(e) => e.stopPropagation()}
                />
              ) : (
                <h3 className="mt-1 text-sm font-medium text-slate-900">{stop.name}</h3>
              )}

              {editable ? (
                <textarea
                  value={stop.note}
                  onChange={(e) => updateStop(idx, { note: e.target.value })}
                  className="mt-1 w-full rounded border border-slate-200 px-1 py-0.5 text-xs text-slate-700"
                  rows={2}
                  onClick={(e) => e.stopPropagation()}
                />
              ) : (
                stop.note && <p className="mt-1 text-xs text-slate-600">{stop.note}</p>
              )}

              {stop.transport_to_next && (
                <p className="mt-1 text-[11px] text-slate-500">→ {stop.transport_to_next}</p>
              )}

              {editable && (
                <div className="mt-2 flex items-center gap-1 border-t border-slate-100 pt-2 text-[11px]">
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation()
                      moveStop(idx, -1)
                    }}
                    className="rounded px-2 py-0.5 hover:bg-slate-100"
                    disabled={idx === 0}
                  >
                    ↑
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation()
                      moveStop(idx, 1)
                    }}
                    className="rounded px-2 py-0.5 hover:bg-slate-100"
                    disabled={idx === itinerary.stops.length - 1}
                  >
                    ↓
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation()
                      removeStop(idx)
                    }}
                    className="ml-auto rounded px-2 py-0.5 text-rose-600 hover:bg-rose-50"
                  >
                    刪除
                  </button>
                </div>
              )}
            </div>
          </li>
        ))}
      </ol>
    </div>
  )
}
