'use client'

import { useState } from 'react'
import clsx from 'clsx'
import { useTranslations } from 'next-intl'
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

const DIET_IDS: Diet[] = ['none', 'vegetarian', 'halal', 'other']
const MOBILITY_IDS: Mobility[] = ['normal', 'low_walking']
const TRANSPORT_IDS: { id: Transport; emoji: string }[] = [
  { id: 'public', emoji: '🚇' },
  { id: 'walk', emoji: '🚶' },
  { id: 'bike', emoji: '🚲' },
]
const PACE_IDS: Pace[] = ['compact', 'normal', 'leisurely']
const THEME_IDS: Theme[] = ['food', 'nature', 'arts', 'shopping', 'history']

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
    pace: pick(PACE_IDS),
    transport: pickN(['public', 'walk', 'bike'] as const, 1, 2) as Transport[],
    districts: pickN(TAIPEI_DISTRICTS, 1, 3) as District[],
    themes: pickN(THEME_IDS, 1, 3),
  }
}

export interface TripWizardProps {
  places: Place[]
  initial?: Partial<TripPreferences>
  initialTitle?: string
  submitLabelKey?: 'submit' | 'submitWithIcon'
  onSubmit: (title: string, prefs: TripPreferences) => void
  onCancel?: () => void
}

export default function TripWizard({
  places,
  initial,
  initialTitle = '',
  submitLabelKey = 'submitWithIcon',
  onSubmit,
  onCancel,
}: TripWizardProps) {
  const t = useTranslations()
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

  const stepKeys: ('basic' | 'preferences' | 'mustVisit')[] = [
    'basic',
    'preferences',
    'mustVisit',
  ]
  const canSubmit = title.trim().length > 0 && prefs.dateStart <= prefs.dateEnd
  const days = tripDayCount(prefs)

  return (
    <section className="rounded-xl border border-slate-200 bg-white shadow-sm">
      <header className="border-b border-slate-200 px-5 py-4">
        <h1 className="text-lg font-semibold text-slate-900">{t('tripWizard.title')}</h1>
        <ol className="mt-3 flex items-center gap-2 text-xs">
          {stepKeys.map((s, i) => (
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
                {t(`tripWizard.steps.${s}` as any)}
              </span>
              {i < stepKeys.length - 1 && <span className="text-slate-300">→</span>}
            </li>
          ))}
        </ol>
      </header>

      <div className="space-y-6 px-5 py-5">
        {step === 0 && (
          <div className="space-y-4">
            <Field label={t('tripWizard.tripName')} required>
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder={t('tripWizard.tripNamePlaceholder')}
                className="input"
              />
            </Field>

            <div className="grid grid-cols-2 gap-3">
              <Field label={t('tripWizard.dateStart')}>
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
              <Field label={t('tripWizard.dateEnd')}>
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
              {days === 1
                ? t('tripWizard.singleDay')
                : t('tripWizard.multiDay', { days })}
            </p>

            <div className="grid grid-cols-2 gap-3">
              <Field label={t('tripWizard.dayStart')}>
                <input
                  type="time"
                  value={prefs.startTime}
                  onChange={(e) => update('startTime', e.target.value)}
                  className="input"
                />
              </Field>
              <Field label={t('tripWizard.dayEnd')}>
                <input
                  type="time"
                  value={prefs.endTime}
                  onChange={(e) => update('endTime', e.target.value)}
                  className="input"
                />
              </Field>
            </div>

            <Field label={t('tripWizard.diet')}>
              <PillGroup
                items={DIET_IDS.map((id) => ({
                  id,
                  label: t(`tripWizard.dietOptions.${id}` as any),
                }))}
                value={prefs.diet}
                onChange={(v) => update('diet', v as Diet)}
              />
              <input
                type="text"
                value={prefs.dietNote}
                onChange={(e) => update('dietNote', e.target.value)}
                placeholder={
                  prefs.diet === 'other'
                    ? t('tripWizard.dietOtherPlaceholder')
                    : t('tripWizard.dietExtraPlaceholder')
                }
                className="input mt-2"
              />
            </Field>

            <Field label={t('tripWizard.mobility')}>
              <div className="grid grid-cols-2 gap-2">
                {MOBILITY_IDS.map((id) => (
                  <button
                    key={id}
                    type="button"
                    onClick={() => update('mobility', id)}
                    className={clsx(
                      'rounded-lg border px-3 py-2 text-left text-sm transition',
                      prefs.mobility === id
                        ? 'border-blue-400 bg-blue-50 text-blue-700'
                        : 'border-slate-200 hover:border-slate-300',
                    )}
                  >
                    <div className="font-medium">
                      {t(
                        `tripWizard.mobilityOptions.${
                          id === 'normal' ? 'normalLabel' : 'lowLabel'
                        }` as any,
                      )}
                    </div>
                    <div className="text-[11px] text-slate-500">
                      {t(
                        `tripWizard.mobilityOptions.${
                          id === 'normal' ? 'normalHint' : 'lowHint'
                        }` as any,
                      )}
                    </div>
                  </button>
                ))}
              </div>
            </Field>

            <Field label={t('tripWizard.budget', { amount: prefs.budget.toLocaleString() })}>
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
                      {t('tripWizard.lucky.label')}
                    </span>
                    {prefs.luckyPick && (
                      <button
                        type="button"
                        onClick={reroll}
                        className="rounded-full border border-amber-300 bg-white px-2 py-0.5 text-[11px] text-amber-700 hover:bg-amber-100"
                      >
                        {t('tripWizard.lucky.reroll')}
                      </button>
                    )}
                  </div>
                  <p className="mt-1 text-xs text-slate-600">
                    {t('tripWizard.lucky.explain')}
                    {prefs.luckyPick && ' ' + t('tripWizard.lucky.applied')}
                  </p>
                </div>
              </label>
            </div>

            <Field label={t('tripWizard.pace')}>
              <div className="grid grid-cols-3 gap-2">
                {PACE_IDS.map((id) => (
                  <button
                    key={id}
                    type="button"
                    onClick={() => update('pace', id)}
                    className={clsx(
                      'rounded-lg border px-3 py-2 text-left text-sm transition',
                      prefs.pace === id
                        ? 'border-blue-400 bg-blue-50 text-blue-700'
                        : 'border-slate-200 hover:border-slate-300',
                    )}
                  >
                    <div className="font-medium">
                      {t(`tripWizard.paceOptions.${id}Label` as any)}
                    </div>
                    <div className="text-[11px] text-slate-500">
                      {t(`tripWizard.paceOptions.${id}Hint` as any)}
                    </div>
                  </button>
                ))}
              </div>
            </Field>

            <Field label={t('tripWizard.transport')}>
              <div className="grid grid-cols-3 gap-2">
                {TRANSPORT_IDS.map((tr) => {
                  const checked = prefs.transport.includes(tr.id)
                  return (
                    <button
                      key={tr.id}
                      type="button"
                      onClick={() =>
                        update('transport', toggleArr<Transport>(prefs.transport, tr.id))
                      }
                      className={clsx(
                        'rounded-lg border px-3 py-2 text-sm transition',
                        checked
                          ? 'border-blue-400 bg-blue-50 text-blue-700'
                          : 'border-slate-200 hover:border-slate-300',
                      )}
                    >
                      <div className="text-lg">{tr.emoji}</div>
                      <div className="text-xs font-medium">
                        {t(`tripWizard.transportOptions.${tr.id}` as any)}
                      </div>
                    </button>
                  )
                })}
              </div>
              {prefs.transport.length === 0 && (
                <p className="mt-1 text-[11px] text-rose-500">
                  {t('tripWizard.transportRequired')}
                </p>
              )}
            </Field>

            <Field label={t('tripWizard.districts')}>
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
                    {t(`tripWizard.districtNames.${d}` as any)}
                  </button>
                ))}
              </div>
            </Field>

            <Field label={t('tripWizard.themes')}>
              <div className="flex flex-wrap gap-1.5">
                {THEME_IDS.map((th) => (
                  <button
                    key={th}
                    type="button"
                    onClick={() => update('themes', toggleArr<Theme>(prefs.themes, th))}
                    className={clsx(
                      'rounded-full border px-2.5 py-1 text-xs transition',
                      prefs.themes.includes(th)
                        ? 'border-amber-400 bg-amber-50 text-amber-700'
                        : 'border-slate-200 text-slate-600 hover:border-slate-300',
                    )}
                  >
                    {t(`tripWizard.themeOptions.${th}` as any)}
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
                  {t('tripWizard.themeOptions.custom')}
                </button>
              </div>
              {prefs.themes.includes('custom') && (
                <input
                  type="text"
                  value={prefs.customTheme}
                  onChange={(e) => update('customTheme', e.target.value)}
                  placeholder={t('tripWizard.customThemePlaceholder')}
                  className="input mt-2"
                />
              )}
            </Field>

            <Field label={t('tripWizard.expectation')}>
              <textarea
                value={prefs.expectation}
                onChange={(e) => update('expectation', e.target.value)}
                rows={3}
                placeholder={t('tripWizard.expectationPlaceholder')}
                className="input"
              />
            </Field>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-3">
            <p className="text-xs text-slate-500">{t('tripWizard.mustVisitHint')}</p>
            {places.length === 0 ? (
              <div className="rounded bg-slate-50 px-3 py-6 text-center text-xs text-slate-500">
                {t('tripWizard.mustVisitEmpty')}
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
              {t('tripWizard.luckyMixNote')}
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
          {t('common.cancel')}
        </button>
        <div className="flex items-center gap-2">
          {step > 0 && (
            <button
              type="button"
              onClick={() => setStep((s) => s - 1)}
              className="rounded-md border border-slate-200 px-3 py-1.5 text-sm text-slate-700 hover:border-slate-300"
            >
              {t('common.back')}
            </button>
          )}
          {step < stepKeys.length - 1 ? (
            <button
              type="button"
              onClick={() => setStep((s) => s + 1)}
              disabled={step === 0 && title.trim().length === 0}
              className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              {t('common.next')}
            </button>
          ) : (
            <button
              type="button"
              onClick={() => canSubmit && onSubmit(title.trim(), prefs)}
              disabled={!canSubmit}
              className="rounded-md bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              {t(`tripWizard.${submitLabelKey}` as any)}
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
