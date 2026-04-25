// Supported locales for Taipei WanderGuard UI.
// Add a new locale here, then drop a matching `messages/<locale>.json`.

export const locales = ['zh-TW', 'zh-CN', 'en', 'ja', 'ko'] as const
export type Locale = (typeof locales)[number]

export const defaultLocale: Locale = 'zh-TW'

export const LOCALE_COOKIE = 'wg_locale'

export const localeLabels: Record<Locale, string> = {
  'zh-TW': '繁體中文',
  'zh-CN': '简体中文',
  en: 'English',
  ja: '日本語',
  ko: '한국어',
}

export function isLocale(value: string): value is Locale {
  return (locales as readonly string[]).includes(value)
}
