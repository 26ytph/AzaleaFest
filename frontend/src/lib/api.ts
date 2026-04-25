// HTTP API client (spec M0.4 / M6.2).
// All UI code goes through `api.*`. When NEXT_PUBLIC_USE_MOCK=true, returns mock data.

import type {
  Place,
  PlaceCreate,
  RecommendResult,
  HotelVerifyResult,
  Itinerary,
} from './types'
import {
  mockPlaces,
  mockRecommendations,
  mockHotelVerify,
  mockItinerary,
} from './mock'

const USE_MOCK = process.env.NEXT_PUBLIC_USE_MOCK === 'true'
const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

const SESSION_STORAGE_KEY = 'wg_session_id'

export function getSessionId(): string {
  if (typeof window === 'undefined') return 'ssr'
  // 從 Line bot 訊息點進來的入口會帶 ?session=...，覆寫 localStorage 後讓
  // 同一個 session_id 在 web / Line 兩端打通。
  const fromUrl = new URLSearchParams(window.location.search).get('session')
  if (fromUrl) {
    window.localStorage.setItem(SESSION_STORAGE_KEY, fromUrl)
    return fromUrl
  }
  let id = window.localStorage.getItem(SESSION_STORAGE_KEY)
  if (!id) {
    id =
      typeof crypto !== 'undefined' && 'randomUUID' in crypto
        ? crypto.randomUUID()
        : Math.random().toString(36).slice(2)
    window.localStorage.setItem(SESSION_STORAGE_KEY, id)
  }
  return id
}

async function request<T>(
  path: string,
  init?: RequestInit & { query?: Record<string, string | number | undefined> },
): Promise<T> {
  const { query, ...rest } = init ?? {}
  const url = new URL(path, BASE_URL)
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined && v !== null) url.searchParams.set(k, String(v))
    }
  }
  const res = await fetch(url.toString(), {
    ...rest,
    headers: {
      'Content-Type': 'application/json',
      ...(rest.headers ?? {}),
    },
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`API ${res.status} ${res.statusText}: ${text || path}`)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

// In-memory mock state so that POST/DELETE behave plausibly during dev.
let mockPlaceState: Place[] = mockPlaces.map((p) => ({ ...p }))
let mockNextId = 1000

export const api = {
  async getPlaces(sessionId: string): Promise<Place[]> {
    if (USE_MOCK) {
      return mockPlaceState.filter((p) => p.user_session_id === sessionId || p.user_session_id === 'dev')
    }
    return request<Place[]>('/places', { query: { session_id: sessionId } })
  },

  async addPlace(data: PlaceCreate): Promise<Place> {
    if (USE_MOCK) {
      const place: Place = {
        id: ++mockNextId,
        user_session_id: data.session_id,
        name: data.name,
        category: data.category,
        lat: data.lat,
        lng: data.lng,
        address: data.address ?? null,
        description: data.description ?? null,
        source_type: data.source_type,
        source_url: data.source_url ?? null,
        hotel_legal_status: data.category === 'hotel' ? 'unknown' : null,
        created_at: new Date().toISOString(),
      }
      mockPlaceState = [place, ...mockPlaceState]
      return place
    }
    return request<Place>('/places', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  async deletePlace(id: number, sessionId: string): Promise<void> {
    if (USE_MOCK) {
      mockPlaceState = mockPlaceState.filter((p) => p.id !== id)
      return
    }
    await request<void>(`/places/${id}`, {
      method: 'DELETE',
      query: { session_id: sessionId },
    })
  },

  async verifyHotel(name: string, lat: number, lng: number): Promise<HotelVerifyResult> {
    if (USE_MOCK) return mockHotelVerify
    return request<HotelVerifyResult>('/hotels/verify', {
      query: { name, lat, lng },
    })
  },

  async getRecommendations(
    sessionId: string,
    category: string,
    limit = 5,
  ): Promise<RecommendResult[]> {
    if (USE_MOCK) {
      const items =
        category === 'all'
          ? mockRecommendations
          : mockRecommendations.filter((r) => r.attraction.category === category)
      return items.slice(0, limit)
    }
    return request<RecommendResult[]>('/recommend', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, category, limit }),
    })
  },

  async generateItinerary(
    sessionId: string,
    date: string,
    startTime?: string,
  ): Promise<Itinerary> {
    if (USE_MOCK) {
      // Echo a stable mock so the UI can render the timeline.
      return { ...mockItinerary }
    }
    return request<Itinerary>('/itinerary/generate', {
      method: 'POST',
      body: JSON.stringify({
        session_id: sessionId,
        date,
        start_time: startTime,
      }),
    })
  },
}
