// Frontend-only types for the trip planning extension.
// Spec types (Place / Itinerary / etc.) live in types.ts and remain authoritative.

import type { Itinerary } from './types'

export type Diet = 'none' | 'vegetarian' | 'halal' | 'other'
export type Mobility = 'normal' | 'low_walking'
export type Transport = 'public' | 'walk' | 'bike'
export type Pace = 'compact' | 'normal' | 'leisurely'
export type Theme =
  | 'food'
  | 'nature'
  | 'arts'
  | 'shopping'
  | 'history'
  | 'custom'

export const TAIPEI_DISTRICTS = [
  '中正區', '大同區', '中山區', '松山區', '大安區', '萬華區',
  '信義區', '士林區', '北投區', '內湖區', '南港區', '文山區',
] as const
export type District = (typeof TAIPEI_DISTRICTS)[number]

export interface TripPreferences {
  dateStart: string               // YYYY-MM-DD (inclusive)
  dateEnd: string                 // YYYY-MM-DD (inclusive; equals dateStart for single-day)
  startTime: string               // HH:MM
  endTime: string                 // HH:MM
  diet: Diet
  dietNote: string                // free-text dietary requirement (used when diet === 'other' or as supplement)
  mobility: Mobility
  pace: Pace
  budget: number                  // NTD per person per day
  transport: Transport[]          // multi-select
  districts: District[]
  themes: Theme[]
  customTheme: string
  expectation: string
  luckyPick: boolean              // when true, AI auto-fills the rest
  mustVisitPlaceIds: number[]     // user-curated places that MUST be in the itinerary
}

export interface ChatTurn {
  role: 'user' | 'assistant'
  content: string
  ts: string
}

export interface TripPlan {
  id: string                      // uuid
  title: string
  preferences: TripPreferences
  itinerary: Itinerary | null
  history: ChatTurn[]
  createdAt: string
  updatedAt: string
}

const today = new Date().toISOString().slice(0, 10)

export const DEFAULT_PREFERENCES: TripPreferences = {
  dateStart: today,
  dateEnd: today,
  startTime: '09:00',
  endTime: '21:00',
  diet: 'none',
  dietNote: '',
  mobility: 'normal',
  pace: 'normal',
  budget: 1500,
  transport: ['public'],
  districts: [],
  themes: [],
  customTheme: '',
  expectation: '',
  luckyPick: false,
  mustVisitPlaceIds: [],
}

export function tripDayCount(prefs: Pick<TripPreferences, 'dateStart' | 'dateEnd'>): number {
  const start = new Date(prefs.dateStart)
  const end = new Date(prefs.dateEnd)
  const ms = end.getTime() - start.getTime()
  return Math.max(1, Math.round(ms / 86_400_000) + 1)
}
