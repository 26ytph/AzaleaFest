'use client'

import { useLocale, useTranslations } from 'next-intl'
import { useTransition } from 'react'

import { LOCALE_COOKIE, locales, localeLabels, type Locale } from '@/i18n/config'

export default function LanguageSwitcher() {
  const locale = useLocale() as Locale
  const t = useTranslations('language')
  const [pending, startTransition] = useTransition()

  const handleChange = (next: Locale) => {
    if (next === locale) return
    // Persist the choice via cookie; refresh swaps server-rendered messages.
    document.cookie = `${LOCALE_COOKIE}=${next}; path=/; max-age=${60 * 60 * 24 * 365}`
    startTransition(() => {
      // Hard reload so next-intl/server re-reads the cookie and dynamic html
      // lang updates everywhere.
      window.location.reload()
    })
  }

  return (
    <label className="relative inline-flex items-center text-xs text-slate-600">
      <span className="sr-only">{t('switch')}</span>
      <select
        aria-label={t('label')}
        value={locale}
        disabled={pending}
        onChange={(e) => handleChange(e.target.value as Locale)}
        className="cursor-pointer appearance-none rounded border border-slate-200 bg-white py-1 pl-2 pr-6 text-xs text-slate-700 hover:border-slate-300 focus:border-blue-300 focus:outline-none disabled:opacity-60"
      >
        {locales.map((l) => (
          <option key={l} value={l}>
            {localeLabels[l]}
          </option>
        ))}
      </select>
      <span aria-hidden className="pointer-events-none absolute right-1.5 text-slate-400">
        ▾
      </span>
    </label>
  )
}
