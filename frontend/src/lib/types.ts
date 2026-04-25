// 共用型別契約 (spec M0.5)
// 所有元件從這裡 import，不得在元件內自行定義型別

export interface Place {
  id: number
  user_session_id: string
  name: string
  category: 'hotel' | 'food' | 'attraction'
  lat: number
  lng: number
  address: string | null
  description: string | null
  source_type: 'reels_url' | 'image' | 'text' | 'manual'
  source_url: string | null
  hotel_legal_status: 'legal' | 'illegal' | 'unknown' | null
  created_at: string
}

export interface PlaceCreate {
  session_id: string
  name: string
  category: 'hotel' | 'food' | 'attraction'
  lat: number
  lng: number
  address?: string | null
  description?: string | null
  source_type: 'reels_url' | 'image' | 'text' | 'manual'
  source_url?: string | null
}

export interface Attraction {
  id: number
  name: string
  // Backend backfills these via scripts/translate_attractions.py.
  // Frontend reads via pickName(attraction, locale) so missing locales
  // fall back to `name`.
  name_en?: string | null
  name_ja?: string | null
  name_ko?: string | null
  name_zh_cn?: string | null
  category: string
  lat: number
  lng: number
  address: string | null
  description: string | null
  tags: string[]
}

export interface RecommendResult {
  attraction: Attraction
  reason: string
  score: number
}

export interface HotelVerifyResult {
  status: 'legal' | 'illegal' | 'unknown'
  match: { id: number; name: string; address: string; lat: number | null; lng: number | null } | null
  alternatives: { id: number; name: string; address: string }[]
}

export interface ItineraryStop {
  time: string
  place_id: number
  name: string
  duration_min: number
  transport_to_next: string
  note: string
}

export interface Itinerary {
  id: number
  stops: ItineraryStop[]
  total_duration_hours: number
}
