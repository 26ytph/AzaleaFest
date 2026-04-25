'use client'

import { useState } from 'react'
import clsx from 'clsx'
import type { Place } from '@/lib/types'
import {
  type Diet,
  type Mobility,
  type Transport,
  type Theme,
  type District,
  type Pace,
  type TripPreferences,
  TAIPEI_DISTRICTS,
  DEFAULT_PREFERENCES,
  tripDayCount,
} from '@/lib/trip-types'

const DIETS: { id: Diet; label: string }[] = [
  { id: 'none', label: '無限制' },
  { id: 'vegetarian', label: '素食' },
  { id: 'halal', label: '清真' },
  { id: 'other', label: '其他' },
]

const MOBILITY: { id: Mobility; label: string; hint: string }[] = [
  { id: 'normal', label: '一般', hint: '可正常步行' },
  { id: 'low_walking', label: '少走路', hint: '行程偏交通工具，避免長距離步行' },
]

const TRANSPORT: { id: Transport; label: string; emoji: string }[] = [
  { id: 'public', label: '大眾運輸', emoji: '🚇' },
  { id: 'walk', label: '步行', emoji: '🚶' },
  { id: 'bike', label: '自行車', emoji: '🚲' },
]

const PACES: { id: Pace; label: string; hint: string }[] = [
  { id: 'compact', label: '緊湊', hint: '每天 6+ 站，看好看滿' },
  { id: 'normal', label: '一般', hint: '每天 4–5 站' },
  { id: 'leisurely', label: '愜意', hint: '每天 2–3 站，深度體驗' },
]

const THEMES: { id: Theme; label: string }[] = [
  { id: 'food', label: '🍜 美食' },
  { id: 'nature', label: '🏞️ 山水' },
  { id: 'arts', label: '🎨 文藝' },
  { id: 'shopping', label: '🛍️ 購物' },
  { id: 'history', label: '🏯 歷史' },
]

function pick<T>(arr: readonly T[]): T {
  return arr[Math.floor(Math.random() * arr.length)]
}

function pickN<T>(arr: readonly T[], min: number, max: number): T[] {
  const n = min + Math.floor(Math.random() * (max - min + 1))
  const shuffled = [...arr].sort(() => Math.random() - 0.5)
  return shuffled.slice(0, n)
}

function randomizeForLucky(p: TripPreferences): TripPreferences {
  return {
    ...p,
    pace: pick(['compact', 'normal', 'leisurely'] as const),
    transport: pickN(['public', 'walk', 'bike'] as const, 1, 2) as Transport[],
    districts: pickN(TAIPEI_DISTRICTS, 1, 3) as District[],
    themes: pickN(['food', 'nature', 'arts', 'shopping', 'history'] as const, 1, 3) as Theme[],
  }
}

export interface TripWizardProps {
  places: Place[]
  initial?: Partial<TripPreferences>
  initialTitle?: string
  submitLabel?: string
  onSubmit: (title: string, prefs: TripPreferences) => void
  onCancel?: () => void
}

export default function TripWizard({
  places,
  initial,
  initialTitle = '',
  submitLabel = '生成行程',
  onSubmit,
  onCancel,
}: TripWizardProps) {
  const [step, setStep] = useState(0)
  const [title, setTitle] = useState(initialTitle)
  const [prefs, setPrefs] = useState<TripPreferences>({
    ...DEFAULT_PREFERENCES,
    ...(initial ?? {}),
    mustVisitPlaceIds: initial?.mustVisitPlaceIds ?? [],
  })

  const update = <K extends keyof TripPreferences>(k: K, v: TripPreferences[K]) =>
    setPrefs((p) => ({ ...p, [k]: v }))

  const toggleArr = <T,>(arr: T[], v: T): T[] =>
    arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]

  const handleLuckyToggle = (next: boolean) => {
    setPrefs((p) => {
      if (next && !p.luckyPick) return { ...randomizeForLucky(p), luckyPick: true }
      return { ...p, luckyPick: next }
    })
  }

  const reroll = () => setPrefs((p) => randomizeForLucky({ ...p, luckyPick: true }))

  const steps = ['基本資訊', '旅遊偏好', '必去景點']
  const canSubmit = title.trim().length > 0 && prefs.dateStart <= prefs.dateEnd
  const days = tripDayCount(prefs)

  return (
    <section className="rounded-xl border border-slate-200 bg-white shadow-sm">
      <header className="border-b border-slate-200 px-5 py-4">
        <h1 className="text-lg font-semibold text-slate-900">建立新行程</h1>
        <ol className="mt-3 flex items-center gap-2 text-xs">
          {steps.map((s, i) => (
            <li key={s} className="flex items-center gap-2">
              <span
                className={clsx(
                  'flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-semibold',
                  i === step
                    ? 'bg-blue-600 text-white'
                    : i < step
                    ? 'bg-blue-100 text-blue-600'
                    : 'bg-slate-100 text-slate-400',
                )}
              >
                {i + 1}
              </span>
              <span
                className={clsx(
                  i === step ? 'text-slate-900 font-medium' : 'text-slate-500',
                )}
              >
                {s}
              </span>
              {i < steps.length - 1 && <span className="text-slate-300">→</span>}
            </li>
          ))}
        </ol>
      </header>

      <div className="space-y-6 px-5 py-5">
        {step === 0 && (
          <div className="space-y-4">
            <Field label="行程名稱" required>
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="例如：週末大稻埕散步"
                className="input"
              />
            </Field>

            <div className="grid grid-cols-2 gap-3">
              <Field label="開始日期">
                <input
                  type="date"
                  value={prefs.dateStart}
                  onChange={(e) => {
                    const v = e.target.value
                    update('dateStart', v)
                    if (v > prefs.dateEnd) update('dateEnd', v)
                  }}
                  className="input"
                />
              </Field>
              <Field label="結束日期">
                <input
                  type="date"
                  value={prefs.dateEnd}
                  min={prefs.dateStart}
                  onChange={(e) => update('dateEnd', e.target.value)}
                  className="input"
                />
              </Field>
            </div>
            <p className="-mt-1 text-[11px] text-slate-500">
              {days === 1 ? '單日行程' : `${days} 天行程`}
            </p>

            <div className="grid grid-cols-2 gap-3">
              <Field label="每日開始">
                <input
                  type="time"
                  value={prefs.startTime}
                  onChange={(e) => update('startTime', e.target.value)}
                  className="input"
                />
              </Field>
              <Field label="每日結束">
                <input
                  type="time"
                  value={prefs.endTime}
                  onChange={(e) => update('endTime', e.target.value)}
                  className="input"
                />
              </Field>
            </div>

            <Field label="飲食偏好">
              <PillGroup
                items={DIETS.map((d) => ({ id: d.id, label: d.label }))}
                value={prefs.diet}
                onChange={(v) => update('diet', v as Diet)}
              />
              <input
                type="text"
                value={prefs.dietNote}
                onChange={(e) => update('dietNote', e.target.value)}
                placeholder={
                  prefs.diet === 'other'
                    ? '請描述其他飲食需求，例如：低 GI、無麩質、不吃牛...'
                    : '其他補充（過敏、不吃辣、忌蔥蒜...）'
                }
                className="input mt-2"
              />
            </Field>

            <Field label="行動需求">
              <div className="grid grid-cols-2 gap-2">
                {MOBILITY.map((m) => (
                  <button
                    key={m.id}
                    type="button"
                    onClick={() => update('mobility', m.id)}
                    className={clsx(
                      'rounded-lg border px-3 py-2 text-left text-sm transition',
                      prefs.mobility === m.id
                        ? 'border-blue-400 bg-blue-50 text-blue-700'
                        : 'border-slate-200 hover:border-slate-300',
                    )}
                  >
                    <div className="font-medium">{m.label}</div>
                    <div className="text-[11px] text-slate-500">{m.hint}</div>
                  </button>
                ))}
              </div>
            </Field>

            <Field label={`預算（每人每日 NT$ ${prefs.budget.toLocaleString()}）`}>
              <input
                type="range"
                min={500}
                max={10000}
                step={100}
                value={prefs.budget}
                onChange={(e) => update('budget', Number(e.target.value))}
                className="w-full"
              />
              <div className="mt-1 flex justify-between text-[11px] text-slate-500">
                <span>500</span>
                <span>5,000</span>
                <span>10,000</span>
              </div>
            </Field>
          </div>
        )}

        {step === 1 && (
          <div className="space-y-5">
            <div
              className={clsx(
                'rounded-xl border-2 p-4 transition',
                prefs.luckyPick
                  ? 'border-amber-400 bg-amber-50/60'
                  : 'border-dashed border-slate-200',
              )}
            >
              <label className="flex cursor-pointer items-start gap-3">
                <input
                  type="checkbox"
                  checked={prefs.luckyPick}
                  onChange={(e) => handleLuckyToggle(e.target.checked)}
                  className="mt-0.5 h-4 w-4"
                />
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-base font-semibold text-slate-900">
                      🎲 好手氣
                    </span>
                    {prefs.luckyPick && (
                      <button
                        type="button"
                        onClick={reroll}
                        className="rounded-full border border-amber-300 bg-white px-2 py-0.5 text-[11px] text-amber-700 hover:bg-amber-100"
                      >
                        重新抽
                      </button>
                    )}
                  </div>
                  <p className="mt-1 text-xs text-slate-600">
                    讓 AI 隨機決定節奏、交通、地區、主題 — 你只要負責去玩。
                    {prefs.luckyPick && '已隨機填入下方偏好，可手動微調。'}
                  </p>
                </div>
              </label>
            </div>

            <Field label="旅遊節奏">
              <div className="grid grid-cols-3 gap-2">
                {PACES.map((p) => (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => update('pace', p.id)}
                    className={clsx(
                      'rounded-lg border px-3 py-2 text-left text-sm transition',
                      prefs.pace === p.id
                        ? 'border-blue-400 bg-blue-50 text-blue-700'
                        : 'border-slate-200 hover:border-slate-300',
                    )}
                  >
                    <div className="font-medium">{p.label}</div>
                    <div className="text-[11px] text-slate-500">{p.hint}</div>
                  </button>
                ))}
              </div>
            </Field>

            <Field label="交通方式（可複選）">
              <div className="grid grid-cols-3 gap-2">
                {TRANSPORT.map((t) => {
                  const checked = prefs.transport.includes(t.id)
                  return (
                    <button
                      key={t.id}
                      type="button"
                      onClick={() =>
                        update('transport', toggleArr<Transport>(prefs.transport, t.id))
                      }
                      className={clsx(
                        'rounded-lg border px-3 py-2 text-sm transition',
                        checked
                          ? 'border-blue-400 bg-blue-50 text-blue-700'
                          : 'border-slate-200 hover:border-slate-300',
                      )}
                    >
                      <div className="text-lg">{t.emoji}</div>
                      <div className="text-xs font-medium">{t.label}</div>
                    </button>
                  )
                })}
              </div>
              {prefs.transport.length === 0 && (
                <p className="mt-1 text-[11px] text-rose-500">至少選擇一種交通方式</p>
              )}
            </Field>

            <Field label="行政區（可複選；不選代表全台北）">
              <div className="flex flex-wrap gap-1.5">
                {TAIPEI_DISTRICTS.map((d) => (
                  <button
                    key={d}
                    type="button"
                    onClick={() => update('districts', toggleArr<District>(prefs.districts, d))}
                    className={clsx(
                      'rounded-full border px-2.5 py-1 text-xs transition',
                      prefs.districts.includes(d)
                        ? 'border-blue-400 bg-blue-50 text-blue-700'
                        : 'border-slate-200 text-slate-600 hover:border-slate-300',
                    )}
                  >
                    {d}
                  </button>
                ))}
              </div>
            </Field>

            <Field label="主題（可複選）">
              <div className="flex flex-wrap gap-1.5">
                {THEMES.map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => update('themes', toggleArr<Theme>(prefs.themes, t.id))}
                    className={clsx(
                      'rounded-full border px-2.5 py-1 text-xs transition',
                      prefs.themes.includes(t.id)
                        ? 'border-amber-400 bg-amber-50 text-amber-700'
                        : 'border-slate-200 text-slate-600 hover:border-slate-300',
                    )}
                  >
                    {t.label}
                  </button>
                ))}
                <button
                  type="button"
                  onClick={() => update('themes', toggleArr<Theme>(prefs.themes, 'custom'))}
                  className={clsx(
                    'rounded-full border px-2.5 py-1 text-xs transition',
                    prefs.themes.includes('custom')
                      ? 'border-amber-400 bg-amber-50 text-amber-700'
                      : 'border-slate-200 text-slate-600 hover:border-slate-300',
                  )}
                >
                  ✏️ 自訂
                </button>
              </div>
              {prefs.themes.includes('custom') && (
                <input
                  type="text"
                  value={prefs.customTheme}
                  onChange={(e) => update('customTheme', e.target.value)}
                  placeholder="自訂主題：例如 攝影、寵物友善..."
                  className="input mt-2"
                />
              )}
            </Field>

            <Field label="想對 AI 說的旅遊期待">
              <textarea
                value={prefs.expectation}
                onChange={(e) => update('expectation', e.target.value)}
                rows={3}
                placeholder="例如：希望午餐在大安區，下午找個能久坐的咖啡廳寫稿..."
                className="input"
              />
            </Field>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-3">
            <p className="text-xs text-slate-500">
              生成行程時，AI 會自動從你的收藏與推薦景點中挑選 — 這裡只需勾選「一定要排進去」的點。
              不勾也可以，全部交給 AI 決定。
            </p>
            {places.length === 0 ? (
              <div className="rounded bg-slate-50 px-3 py-6 text-center text-xs text-slate-500">
                還沒有收藏地點。回到主頁透過 Line 新增後再回來。
              </div>
            ) : (
              <ul className="max-h-72 space-y-2 overflow-y-auto pr-1">
                {places.map((p) => {
                  const checked = prefs.mustVisitPlaceIds.includes(p.id)
                  return (
                    <li key={p.id}>
                      <label
                        className={clsx(
                          'flex cursor-pointer items-center gap-3 rounded-lg border p-2.5 transition',
                          checked
                            ? 'border-blue-400 bg-blue-50'
                            : 'border-slate-200 hover:border-slate-300',
                        )}
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() =>
                            update(
                              'mustVisitPlaceIds',
                              toggleArr<number>(prefs.mustVisitPlaceIds, p.id),
                            )
                          }
                        />
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-sm font-medium text-slate-900">
                            {p.name}
                          </div>
                          {p.address && (
                            <div className="truncate text-[11px] text-slate-500">
                              {p.address}
                            </div>
                          )}
                        </div>
                        <span className="text-xs text-slate-500">
                          {p.category === 'food'
                            ? '🍽️'
                            : p.category === 'attraction'
                            ? '🏛️'
                            : '🏨'}
                        </span>
                      </label>
                    </li>
                  )
                })}
              </ul>
            )}
            <p className="rounded bg-amber-50 px-3 py-2 text-[11px] text-amber-800">
              無論是否啟用好手氣，AI 都會適度混入推薦景點豐富行程。
            </p>
          </div>
        )}
      </div>

      <footer className="flex items-center justify-between border-t border-slate-200 px-5 py-3">
        <button
          type="button"
          onClick={onCancel}
          className="rounded px-3 py-1.5 text-sm text-slate-500 hover:text-slate-700"
        >
          取消
        </button>
        <div className="flex items-center gap-2">
          {step > 0 && (
            <button
              type="button"
              onClick={() => setStep((s) => s - 1)}
              className="rounded-md border border-slate-200 px-3 py-1.5 text-sm text-slate-700 hover:border-slate-300"
            >
              上一步
            </button>
          )}
          {step < steps.length - 1 ? (
            <button
              type="button"
              onClick={() => setStep((s) => s + 1)}
              className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-500"
            >
              下一步
            </button>
          ) : (
            <button
              type="button"
              onClick={() => canSubmit && onSubmit(title.trim(), prefs)}
              disabled={!canSubmit}
              className="rounded-md bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              ✨ {submitLabel}
            </button>
          )}
        </div>
      </footer>

      <style jsx>{`
        .input {
          width: 100%;
          border-radius: 0.5rem;
          border: 1px solid #e2e8f0;
          padding: 0.5rem 0.75rem;
          font-size: 0.875rem;
          background: white;
        }
        .input:focus {
          outline: none;
          border-color: #60a5fa;
          box-shadow: 0 0 0 2px rgb(96 165 250 / 0.2);
        }
      `}</style>
    </section>
  )
}

function Field({
  label,
  children,
  required,
}: {
  label: string
  children: React.ReactNode
  required?: boolean
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-medium text-slate-700">
        {label} {required && <span className="text-rose-500">*</span>}
      </span>
      {children}
    </label>
  )
}

function PillGroup<T extends string>({
  items,
  value,
  onChange,
}: {
  items: { id: T; label: string }[]
  value: T
  onChange: (v: T) => void
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((it) => (
        <button
          key={it.id}
          type="button"
          onClick={() => onChange(it.id)}
          className={clsx(
            'rounded-full border px-3 py-1 text-xs transition',
            value === it.id
              ? 'border-blue-400 bg-blue-50 text-blue-700'
              : 'border-slate-200 text-slate-600 hover:border-slate-300',
          )}
        >
          {it.label}
        </button>
      ))}
    </div>
  )
}
