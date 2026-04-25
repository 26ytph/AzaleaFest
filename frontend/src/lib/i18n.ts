// Locale-aware helpers shared between server & client components.

import type { Locale } from '@/i18n/config'
import type { Attraction } from './types'

type WithLocaleNames = Pick<
  Attraction,
  'name' | 'name_en' | 'name_ja' | 'name_ko' | 'name_zh_cn'
>

/**
 * Pick the attraction name for the given locale.
 * Falls back to the canonical `name` (zh-TW) if the locale-specific
 * column is null or empty — which is exactly what the backend stores
 * before scripts/translate_attractions.py has filled it in.
 */
export function pickName(a: WithLocaleNames, locale: Locale): string {
  switch (locale) {
    case 'en':
      return a.name_en?.trim() || a.name
    case 'ja':
      return a.name_ja?.trim() || a.name
    case 'ko':
      return a.name_ko?.trim() || a.name
    case 'zh-CN':
      return a.name_zh_cn?.trim() || a.name
    case 'zh-TW':
    default:
      return a.name
  }
}
