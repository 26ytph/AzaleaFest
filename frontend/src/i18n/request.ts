import { cookies, headers } from 'next/headers'
import { getRequestConfig } from 'next-intl/server'

import { defaultLocale, isLocale, locales, LOCALE_COOKIE, type Locale } from './config'

function pickFromAcceptLanguage(header: string | null): Locale | null {
  if (!header) return null
  // Format: zh-TW,zh;q=0.9,en;q=0.8
  for (const part of header.split(',')) {
    const tag = part.split(';')[0].trim()
    if (isLocale(tag)) return tag
    // Try the primary subtag — e.g. "zh" → match "zh-TW" first, "en" → "en"
    const primary = tag.split('-')[0].toLowerCase()
    const fuzzy = locales.find((l) => l.toLowerCase().startsWith(primary))
    if (fuzzy) return fuzzy
  }
  return null
}

export default getRequestConfig(async () => {
  const cookieValue = (await cookies()).get(LOCALE_COOKIE)?.value
  const headerLocale = pickFromAcceptLanguage((await headers()).get('accept-language'))

  const locale: Locale =
    (cookieValue && isLocale(cookieValue) && cookieValue) ||
    headerLocale ||
    defaultLocale

  const messages = (await import(`./messages/${locale}.json`)).default

  return { locale, messages }
})
