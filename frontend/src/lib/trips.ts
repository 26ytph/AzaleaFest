// Frontend-only trip persistence. Spec doesn't define a "list trips" API,
// so trip plans (preferences + chat history + cached itinerary) live in localStorage,
// while the actual itinerary content comes from POST /itinerary/generate.

import type { Itinerary } from './types'
import { mockItinerary } from './mock'
import {
  type TripPlan,
  type TripPreferences,
  DEFAULT_PREFERENCES,
} from './trip-types'

const KEY = 'wg_trips_v1'

function uuid(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  return 't_' + Math.random().toString(36).slice(2, 10)
}

function read(): TripPlan[] {
  if (typeof window === 'undefined') return []
  try {
    const raw = window.localStorage.getItem(KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? (parsed as TripPlan[]) : []
  } catch {
    return []
  }
}

function write(trips: TripPlan[]): void {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(KEY, JSON.stringify(trips))
  window.dispatchEvent(new CustomEvent('wg:trips-changed'))
}

export const tripsStore = {
  list(): TripPlan[] {
    return read().sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
  },

  get(id: string): TripPlan | undefined {
    return read().find((t) => t.id === id)
  },

  create(partial: { title: string; preferences?: Partial<TripPreferences> }): TripPlan {
    const now = new Date().toISOString()
    const trip: TripPlan = {
      id: uuid(),
      title: partial.title || `行程 ${new Date().toLocaleDateString('zh-TW')}`,
      preferences: { ...DEFAULT_PREFERENCES, ...(partial.preferences ?? {}) },
      itinerary: null,
      history: [],
      createdAt: now,
      updatedAt: now,
    }
    write([trip, ...read()])
    return trip
  },

  update(id: string, patch: Partial<TripPlan>): TripPlan | undefined {
    const trips = read()
    const idx = trips.findIndex((t) => t.id === id)
    if (idx === -1) return undefined
    const updated: TripPlan = {
      ...trips[idx],
      ...patch,
      preferences: patch.preferences ?? trips[idx].preferences,
      updatedAt: new Date().toISOString(),
    }
    trips[idx] = updated
    write(trips)
    return updated
  },

  setItinerary(id: string, itinerary: Itinerary): TripPlan | undefined {
    return tripsStore.update(id, { itinerary })
  },

  appendChat(id: string, role: 'user' | 'assistant', content: string): TripPlan | undefined {
    const trip = tripsStore.get(id)
    if (!trip) return undefined
    const history = [...trip.history, { role, content, ts: new Date().toISOString() }]
    return tripsStore.update(id, { history })
  },

  remove(id: string): void {
    write(read().filter((t) => t.id !== id))
  },

  /** Insert a demo trip if storage is empty. Returns true if seeded. */
  seedSampleIfEmpty(): boolean {
    if (read().length > 0) return false
    write([buildSampleTrip()])
    return true
  },
}

const SAMPLE_ID = 'sample-trip-demo'

function buildSampleTrip(): TripPlan {
  const today = new Date()
  const start = today.toISOString().slice(0, 10)
  const end = new Date(today.getTime() + 86_400_000).toISOString().slice(0, 10)
  const now = new Date().toISOString()
  const earlier = new Date(today.getTime() - 5 * 60_000).toISOString()
  const earlier2 = new Date(today.getTime() - 3 * 60_000).toISOString()

  const preferences: TripPreferences = {
    ...DEFAULT_PREFERENCES,
    dateStart: start,
    dateEnd: end,
    startTime: '09:30',
    endTime: '21:00',
    diet: 'none',
    dietNote: '不太能吃辣',
    mobility: 'normal',
    pace: 'normal',
    budget: 1800,
    transport: ['public', 'walk'],
    districts: ['大同區', '大安區', '信義區'],
    themes: ['food', 'history'],
    customTheme: '',
    expectation: '想要早上散步、午餐找老店，傍晚有夕陽景觀，晚上回飯店。',
    luckyPick: false,
    mustVisitPlaceIds: [1, 3], // 永康牛肉麵、大稻埕碼頭（對應 mock.ts）
  }

  const itinerary: Itinerary = {
    ...mockItinerary,
    id: 9999,
  }

  return {
    id: SAMPLE_ID,
    title: '範例：大稻埕 × 信義區 兩日輕旅行',
    preferences,
    itinerary,
    history: [
      {
        role: 'assistant',
        content:
          '已根據你的偏好生成 6 站、約 9 小時的行程。包含早晨大稻埕散步、午餐永康牛肉麵、下午富錦街咖啡，傍晚四四南村看夕陽。可以告訴我要怎麼修改。',
        ts: earlier,
      },
      {
        role: 'user',
        content: '把午餐換成清淡一點的選項',
        ts: earlier2,
      },
      {
        role: 'assistant',
        content:
          '好，把 12:30 的牛肉麵改成迪化街老屋茶館的台式定食。需要的話也可以幫你把下午咖啡換成更安靜的工作室類型。',
        ts: now,
      },
    ],
    createdAt: now,
    updatedAt: now,
  }
}
