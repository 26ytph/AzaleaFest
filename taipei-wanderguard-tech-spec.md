# Taipei WanderGuard — 技術架構規格書 v2
> **使用原則**：每個 Module 是獨立開發單元。成員 A 可以只讀 M3 + M5，成員 B 只讀 M4 + M6，互不干擾。
> Claude Code 使用方式：直接把單一 Module 的內容貼給 agent，不需要提供其他 Module。
> Module 間的溝通邊界全部透過 **HTTP API contract** 或 **DB table interface** 定義在各 Module 開頭。

---

## 全域索引

| Module | 名稱 | 依賴 | MVP 必要 |
|--------|------|------|----------|
| [M0](#m0-專案底層-infrastructure) | 專案底層 Infrastructure | — | ✅ |
| [M1](#m1-景點知識庫-osm-ingest) | 景點知識庫 OSM Ingest | M0 | ✅ |
| [M2](#m2-ig-reels-媒體管線) | IG Reels 媒體管線 | M0 | ✅ |
| [M3](#m3-line-bot-入口) | Line Bot 入口 | M0, M2 | ✅ |
| [M4](#m4-旅宿守門員) | 旅宿守門員 | M0 | ✅ |
| [M5](#m5-rag-推薦引擎) | RAG 推薦引擎 | M0, M1 | ✅ |
| [M6](#m6-前端地圖-ui) | 前端地圖 UI | M0 API contract | ✅ |
| [M7](#m7-行程生成) | 行程生成 | M0, M5 | ⬜ Phase 2 |

---

## M0: 專案底層 Infrastructure

> **所有成員必讀。** 定義共用的 DB schema、環境變數、HTTP contract、目錄結構。
> 各 Module 的 DB table 由負責成員建立，但 schema 定義在此文件統一管理。

### M0.1 目錄結構

```
taipei-wanderguard/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI app + router 掛載
│   │   ├── config.py               # pydantic BaseSettings，讀取所有環境變數
│   │   ├── database.py             # async engine + session factory，所有 Module 共用
│   │   ├── models/                 # SQLAlchemy ORM（schema 定義在 M0，不得自行新增欄位）
│   │   │   ├── attraction.py       # M1 負責
│   │   │   ├── place.py            # M3 負責
│   │   │   ├── hotel.py            # M4 負責
│   │   │   └── itinerary.py        # M7 負責
│   │   ├── routers/                # 每個 Module 一個 router 檔，在 main.py 掛載
│   │   │   ├── webhook.py          # M3
│   │   │   ├── places.py           # M3
│   │   │   ├── hotels.py           # M4
│   │   │   ├── recommend.py        # M5
│   │   │   └── itinerary.py        # M7
│   │   └── services/               # 每個 Module 一個子目錄
│   │       ├── media/              # M2
│   │       ├── hotel/              # M4
│   │       ├── rag/                # M5
│   │       ├── itinerary/          # M7
│   │       ├── embedder.py         # M1+M3+M5 共用，在此統一定義
│   │       └── geocoding.py        # M3 使用
│   ├── scripts/
│   │   ├── ingest_osm.py           # M1: 一次性執行
│   │   └── ingest_hotels.py        # M4: 一次性執行
│   ├── tests/
│   │   ├── test_m2_media.py
│   │   ├── test_m4_hotel.py
│   │   └── test_m5_rag.py
│   ├── alembic/
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/                       # M6
│   ├── src/
│   │   ├── app/
│   │   │   ├── page.tsx
│   │   │   └── layout.tsx
│   │   ├── components/
│   │   │   ├── Map.tsx
│   │   │   ├── Sidebar.tsx
│   │   │   ├── PlaceCard.tsx
│   │   │   ├── RecommendCard.tsx
│   │   │   ├── HotelBadge.tsx
│   │   │   └── ItineraryTimeline.tsx
│   │   ├── hooks/
│   │   │   ├── usePlaces.ts
│   │   │   └── useRecommendations.ts
│   │   └── lib/
│   │       ├── api.ts
│   │       ├── types.ts            # 所有型別定義，各元件不得自行定義
│   │       └── mock.ts             # 開發用 mock data
│   ├── package.json
│   └── Dockerfile
├── docker-compose.yml
└── .env.example
```

### M0.2 環境變數

```bash
# .env.example — 所有成員在開始前確認這些 key 都有值

# DB
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/wanderguard

# Line Bot (M3)
LINE_CHANNEL_SECRET=
LINE_CHANNEL_ACCESS_TOKEN=
WEB_APP_URL=http://localhost:3000

# Google Maps (M3 geocoding, M4 ingest)
GOOGLE_MAPS_API_KEY=

# Anthropic Claude (M2 vision, M5 reason, M7 itinerary)
ANTHROPIC_API_KEY=

# OpenAI (M1 + M3 + M5 embeddings)
OPENAI_API_KEY=

# Mapbox (M6)
NEXT_PUBLIC_MAPBOX_TOKEN=
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_USE_MOCK=false

# 中央氣象局 (M7, optional)
CWB_API_KEY=

# Redis
REDIS_URL=redis://localhost:6379
```

### M0.3 資料庫 Schema（權威定義）

> **規則**：各 Module 只能 READ 其他 Module 的 table，不能 ALTER。
> 需要跨 Module 欄位時，先在此文件更新，再實作 migration。

```sql
-- ===== M1 建立並維護 =====
CREATE TABLE attractions (
    id           SERIAL PRIMARY KEY,
    name         TEXT NOT NULL,
    name_en      TEXT,
    category     TEXT NOT NULL CHECK (category IN ('food', 'attraction', 'hotel')),
    lat          FLOAT NOT NULL,
    lng          FLOAT NOT NULL,
    address      TEXT,
    description  TEXT,
    tags         TEXT[],
    osm_id       BIGINT UNIQUE,
    embedding    vector(1536),
    source       TEXT DEFAULT 'osm',
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ON attractions USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX ON attractions (category);

-- ===== M3 寫入，M5/M6/M7 唯讀 =====
CREATE TABLE places (
    id                 SERIAL PRIMARY KEY,
    user_session_id    TEXT NOT NULL,
    name               TEXT NOT NULL,
    category           TEXT NOT NULL CHECK (category IN ('hotel', 'food', 'attraction')),
    lat                FLOAT NOT NULL,
    lng                FLOAT NOT NULL,
    address            TEXT,
    description        TEXT,
    source_type        TEXT CHECK (source_type IN ('reels_url', 'image', 'text', 'manual')),
    source_url         TEXT,
    reels_caption      TEXT,
    embedding          vector(1536),
    hotel_legal_status TEXT CHECK (hotel_legal_status IN ('legal', 'illegal', 'unknown')),
    hotel_match_id     INT REFERENCES legal_hotels(id),
    created_at         TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ON places (user_session_id);
CREATE INDEX ON places USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ===== M4 建立並維護 =====
CREATE TABLE legal_hotels (
    id             SERIAL PRIMARY KEY,
    name           TEXT NOT NULL,
    address        TEXT NOT NULL,
    lat            FLOAT,
    lng            FLOAT,
    license_number TEXT UNIQUE,
    hotel_type     TEXT,
    source         TEXT,
    raw_data       JSONB,
    updated_at     TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ON legal_hotels USING GIN (to_tsvector('simple', name || ' ' || address));

-- ===== M7 建立並維護 =====
CREATE TABLE itineraries (
    id                 SERIAL PRIMARY KEY,
    user_session_id    TEXT NOT NULL,
    places_snapshot    JSONB,
    schedule           JSONB,
    weather_context    JSONB,
    generated_at       TIMESTAMPTZ DEFAULT NOW()
);
```

**Migration 流程**：

```bash
# 初始化（全員執行一次）
alembic upgrade head

# 新增欄位時（只有 M0 maintainer 執行）
alembic revision --autogenerate -m "add xxx column"
alembic upgrade head
```

### M0.4 HTTP API Contract（前後端邊界）

> M6 只依賴這份 contract，後端成員實作時必須嚴格符合。

```
GET  /places?session_id={str}
     → 200: Place[]

POST /places
     body: PlaceCreate
     → 201: Place

DELETE /places/{id}?session_id={str}
     → 204

GET  /hotels/verify?name={str}&lat={float}&lng={float}
     → 200: HotelVerifyResult

POST /recommend
     body: { session_id: str, category: str, limit?: int }
     → 200: RecommendResult[]

POST /itinerary/generate
     body: { session_id: str, date: str, start_time?: str }
     → 200: Itinerary
```

### M0.5 共用型別（TypeScript）

```typescript
// frontend/src/lib/types.ts
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

export interface Attraction {
  id: number
  name: string
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
```

### M0.6 Docker Compose

```yaml
version: '3.9'
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: wanderguard
      POSTGRES_USER: user
      POSTGRES_PASSWORD: password
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U user -d wanderguard"]
      interval: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  backend:
    build: ./backend
    env_file: .env
    ports:
      - "8000:8000"
    depends_on:
      db:
        condition: service_healthy
    volumes:
      - /tmp:/tmp   # M2: yt-dlp 暫存

  frontend:
    build: ./frontend
    env_file: .env
    ports:
      - "3000:3000"
    depends_on:
      - backend

volumes:
  pgdata:
```

### M0.7 Requirements

```
# backend/requirements.txt

# Core
fastapi==0.115.0
uvicorn[standard]==0.30.0
sqlalchemy[asyncio]==2.0.35
asyncpg==0.29.0
pgvector==0.3.2
alembic==1.13.2
pydantic-settings==2.5.2
httpx==0.27.2
numpy==1.26.4

# M2
anthropic==0.34.0
yt-dlp==2024.9.27
opencv-python-headless==4.10.0.84

# M3
line-bot-sdk==3.11.0

# M4
rapidfuzz==3.9.7

# M1, M3, M5
openai==1.45.0

# M7
apscheduler==3.10.4
```

---

## M1: 景點知識庫 OSM Ingest

> **依賴**: M0 (`attractions` table schema, `embedder.py`)
> **產出**: 填滿 `attractions` table，供 M5 RAG 使用
> **執行時機**: Hackathon Day 1 一開始在背景跑，約 10–15 分鐘完成

### M1 的職責邊界

- ✅ 從 Overpass API 取台北市 POI
- ✅ 寫入並維護 `attractions` table
- ✅ 計算並填入 `attractions.embedding`
- ❌ 不接觸 `places`、`legal_hotels`、`itineraries`
- ❌ 不提供任何 HTTP endpoint（純 offline script）

### M1.1 OSM 資料來源

Overpass API，免費，無需 API key。

目標 OSM tag：

```
amenity = restaurant, cafe, bar, fast_food, food_court, ice_cream
tourism = attraction, museum, gallery, viewpoint, theme_park
leisure = park, garden, sports_centre
shop    = mall, department_store, market
```

預期：台北市約 8,000–12,000 筆 POI，去重後存入 `attractions`。

### M1.2 Ingest Script

**Claude Code prompt for M1**:
> 實作 `scripts/ingest_osm.py`，符合以下所有函式規格，使用 asyncio + httpx + SQLAlchemy async。

```python
# scripts/ingest_osm.py
"""
執行方式: python scripts/ingest_osm.py
預期執行時間: 10–15 分鐘（含 embedding batch）
需要環境變數: DATABASE_URL, OPENAI_API_KEY
"""

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

OVERPASS_QUERY = """
[out:json][timeout:120];
area["name"="臺北市"]["admin_level"="4"]->.taipei;
(
  node["amenity"~"^(restaurant|cafe|bar|fast_food|food_court|ice_cream)$"](area.taipei);
  node["tourism"~"^(attraction|museum|gallery|viewpoint|theme_park)$"](area.taipei);
  node["leisure"~"^(park|garden|sports_centre)$"](area.taipei);
  node["shop"~"^(mall|department_store|market)$"](area.taipei);
);
out body;
"""

TAG_TO_CATEGORY = {
    "restaurant": "food", "cafe": "food", "bar": "food",
    "fast_food": "food", "food_court": "food", "ice_cream": "food",
    "attraction": "attraction", "museum": "attraction", "gallery": "attraction",
    "viewpoint": "attraction", "theme_park": "attraction",
    "park": "attraction", "garden": "attraction", "sports_centre": "attraction",
    "mall": "attraction", "department_store": "attraction", "market": "food",
}

def parse_osm_element(el: dict) -> dict | None:
    """
    從 OSM element 提取欄位。回傳 None 表示跳過。

    OSM element 結構:
    { "id": 123456, "lat": 25.04, "lon": 121.51,
      "tags": { "name": "鼎泰豐", "amenity": "restaurant", ... } }

    規則:
    - tags['name'] 或 tags['name:zh'] 都沒有 → 回傳 None
    - 取第一個匹配到 TAG_TO_CATEGORY 的 tag 值作為 category
    - description = 組合 cuisine / opening_hours / wheelchair 等 tag（有什麼用什麼）
    - tags list = [amenity_value, cuisine（若有）]
    """

def build_embed_text(row: dict) -> str:
    """
    組合 embedding 輸入字串。
    格式: "{name}。{category}。{address}。{description}。{tags joined}"
    範例: "鼎泰豐。food。台北市信義區信義路五段。台式料理。restaurant taiwanese"
    """

async def fetch_osm_data() -> list[dict]:
    """
    POST OVERPASS_URL，body={"data": OVERPASS_QUERY}，timeout=120s。
    回傳 response.json()["elements"]。
    失敗 → 拋出 RuntimeError。
    """

async def batch_embed(texts: list[str], client: AsyncOpenAI) -> list[list[float]]:
    """
    每 100 筆一批打 OpenAI text-embedding-3-small。
    每批之間 await asyncio.sleep(0.5)。
    回傳與 texts 等長的 embedding list。
    """

async def ingest():
    """
    主流程:
    1. fetch_osm_data() → elements（約 15,000 筆含重複）
    2. [parse_osm_element(el) for el in elements]，過濾 None → valid_rows
    3. 查 DB 已有的 osm_id set，從 valid_rows 排除
    4. build_embed_text() 組合輸入
    5. batch_embed() 計算 embedding
    6. 批次 INSERT INTO attractions，ON CONFLICT (osm_id) DO NOTHING
    7. 清除暫存 /tmp/*.mp4, /tmp/*.jpg（若有）
    8. 印出統計: Fetched X / Valid Y / Skipped Z / Inserted W / Time T秒

    try/except 包住每個 parse，失敗跳過不 crash。
    """
```

### M1.3 驗收條件

```bash
python scripts/ingest_osm.py
# 預期輸出:
# Fetched 14832 OSM elements
# Valid: 9241 | Skipped (exist): 0 | Inserted: 9241 | Time: 623s

psql -c "SELECT category, COUNT(*) FROM attractions GROUP BY category;"
#  food: ~5000, attraction: ~4000
```

---

## M2: IG Reels 媒體管線

> **依賴**: M0 (config, Anthropic API key)
> **被依賴**: M3 呼叫 `process_reels_url()` 和 `process_image_bytes()`
> **職責**: 給定 IG Reels URL → 回傳結構化地點資訊

### M2 的職責邊界

- ✅ 下載 Reels（yt-dlp）、提取 keyframe（OpenCV）、呼叫 Claude Vision
- ✅ 回傳 `ExtractedContent` dataclass
- ❌ **不寫任何 DB**（資料持久化是 M3 的責任）
- ❌ **不處理 Line event**（那是 M3 的事）
- ❌ 不處理非 IG URL（未來擴充其他平台時新增函式，不修改現有函式）

### M2.1 公開介面（M3 只能 import 這些）

```python
# app/services/media/__init__.py

from dataclasses import dataclass

@dataclass
class ExtractedContent:
    name: str           # 地點名稱
    category: str       # 'food' | 'attraction' | 'hotel'
    description: str    # 50 字以內
    address_hint: str   # 地址線索，可為空字串
    caption: str        # yt-dlp info_dict['description']，原始 caption
    confidence: float   # 0.0–1.0

class DownloadError(Exception):
    """yt-dlp 下載失敗（私人帳號、地區限制等）"""

async def process_reels_url(url: str) -> ExtractedContent:
    """M3 呼叫的唯一入口（IG Reels URL）"""

async def process_image_bytes(image_bytes: bytes) -> ExtractedContent:
    """M3 呼叫的唯一入口（使用者上傳圖片）"""
```

### M2.2 實作規格

**Claude Code prompt for M2**:
> 實作 `app/services/media/` 目錄，包含 `downloader.py`、`extractor.py`、`vision.py`、`__init__.py`，符合以下規格。

```python
# app/services/media/downloader.py

async def download_reels(url: str) -> tuple[str, str]:
    """
    用 yt-dlp 下載 IG Reels。

    ydl_opts = {
        'format': 'best[height<=480]',
        'outtmpl': f'/tmp/{uuid4()}.%(ext)s',
        'quiet': True,
        'no_warnings': True,
    }

    yt-dlp download() 是同步的，用 asyncio.to_thread() 包裝。

    回傳: (video_path: str, caption: str)
    - caption = info_dict.get('description', '')
    - 下載失敗 → 拋出 DownloadError(原始錯誤訊息)
    """
```

```python
# app/services/media/extractor.py

def extract_keyframe(video_path: str, second: int = 3) -> str:
    """
    用 OpenCV 取影片第 {second} 秒的 frame，存為 /tmp/{uuid}.jpg。

    步驟:
    1. cap = cv2.VideoCapture(video_path)
    2. fps = cap.get(cv2.CAP_PROP_FPS)
    3. target_frame = int(fps * second)
    4. 若 target_frame > total_frames，改用 total_frames - 1
    5. cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
    6. ret, frame = cap.read()
    7. cv2.imwrite(jpg_path, frame)
    8. 回傳 jpg_path
    """

def image_to_base64(image_path: str) -> str:
    """讀取 image_path，回傳 base64 encoded string。"""
```

```python
# app/services/media/vision.py

SYSTEM_PROMPT = """你是地點資訊提取助手。從圖片和文字中識別被拍攝的地點。
只回傳 JSON，不包含任何說明文字或 markdown 符號。"""

USER_PROMPT_TEMPLATE = """
圖片如附。
社群媒體原文（可能為空）: {caption}

回傳以下 JSON（無其他文字）:
{{
  "name": "地點名稱（繁體中文優先）",
  "category": "food 或 attraction 或 hotel",
  "description": "50字以內描述",
  "address_hint": "地址線索（無則空字串）",
  "confidence": 0.85
}}

判斷規則:
- confidence < 0.5: 圖片無明顯地點（純食物特寫、人物照等）
- food: 餐廳、咖啡廳、攤位、夜市
- hotel: 旅館、飯店、民宿室內
- attraction: 景點、公園、商場、其他
"""

async def vision_extract(image_base64: str, caption: str) -> dict:
    """
    呼叫 claude-sonnet-4-20250514，messages 格式:
    [{ "role": "user", "content": [
        { "type": "image", "source": { "type": "base64", "media_type": "image/jpeg", "data": image_base64 } },
        { "type": "text", "text": USER_PROMPT_TEMPLATE.format(caption=caption) }
    ]}]

    解析回應為 JSON dict。
    若 JSON 解析失敗，回傳預設值:
    { "name": "", "category": "attraction", "description": "", "address_hint": "", "confidence": 0.0 }
    """
```

```python
# app/services/media/__init__.py

async def process_reels_url(url: str) -> ExtractedContent:
    """
    1. video_path, caption = await download_reels(url)
       DownloadError 直接往上拋，由 M3 catch
    2. frame_path = extract_keyframe(video_path, second=3)
    3. b64 = image_to_base64(frame_path)
    4. extracted = await vision_extract(b64, caption)
    5. try/finally: os.remove(video_path), os.remove(frame_path)
       （無論成功失敗都清暫存檔）
    6. 回傳 ExtractedContent(**extracted, caption=caption)
    """

async def process_image_bytes(image_bytes: bytes) -> ExtractedContent:
    """
    1. b64 = base64.b64encode(image_bytes).decode()
    2. extracted = await vision_extract(b64, caption="")
    3. 回傳 ExtractedContent(**extracted, caption="")
    """
```

### M2.3 驗收條件

```bash
pytest tests/test_m2_media.py -v

# 測試項目:
# test_extract_keyframe_valid        → 給合法 mp4，產生 jpg，檔案存在
# test_extract_keyframe_short_video  → 影片長度 < 3s，仍能取到 frame
# test_vision_extract_mock           → mock Claude API，確認 JSON parsing 正確
# test_vision_extract_fallback       → Claude 回非 JSON，回傳預設值
# test_cleanup_on_failure            → vision_extract 拋出例外時，/tmp 暫存仍被清除
# test_process_reels_url_integration → 給真實公開 IG URL，confidence > 0.5（需要 ANTHROPIC_API_KEY）
```

---

## M3: Line Bot 入口

> **依賴**: M0 (DB, config), M2 (`process_reels_url`, `process_image_bytes`), `services/embedder.py`, `services/geocoding.py`
> **產出**: 寫入 `places` table，回傳 Line reply message

### M3 的職責邊界

- ✅ 接收並驗證 Line webhook event
- ✅ 呼叫 M2 取得 `ExtractedContent`
- ✅ 呼叫 geocoding 取得座標
- ✅ 計算 embedding 並寫入 `places` table
- ✅ 若 category=hotel，非同步觸發 M4 驗證（fire-and-forget）
- ✅ 提供 `GET/POST/DELETE /places` endpoint 給 M6 使用
- ❌ 不實作任何地點解析邏輯（全部交給 M2）
- ❌ 不實作推薦邏輯（那是 M5 的事）

### M3.1 Webhook 處理邏輯

**Claude Code prompt for M3**:
> 實作 `app/routers/webhook.py` 和 `app/services/line_handler.py`，使用 line-bot-sdk v3 async。

```python
# app/routers/webhook.py

# POST /webhook/line
# 1. 從 header 取 X-Line-Signature
# 2. 用 WebhookParser(LINE_CHANNEL_SECRET) 解析 body
# 3. 對每個 event，asyncio.create_task(handle_event(event, line_api))
# 4. 永遠回傳 HTTP 200（Line 要求，不管處理成功與否）
```

```python
# app/services/line_handler.py

import re, hashlib, asyncio
from app.services.media import process_reels_url, process_image_bytes, DownloadError
from app.services.geocoding import geocode, GeocodingError
from app.services.embedder import embed

IG_URL_PATTERN = re.compile(
    r'https?://(www\.)?(instagram\.com|instagr\.am)/reel[s]?/[\w-]+'
)

def get_session_id(user_id: str) -> str:
    """sha256(user_id) 的前 16 碼，不儲存真實 user_id"""
    return hashlib.sha256(user_id.encode()).hexdigest()[:16]

async def handle_event(event, line_api):
    """
    分流:
    TextMessage + IG URL  → handle_reels_url()
    TextMessage + 純文字  → handle_plain_text()
    ImageMessage          → handle_image()
    其他                  → reply("目前支援：IG Reels 連結、圖片、地點名稱文字")
    """

async def handle_reels_url(url: str, reply_token: str, session_id: str, line_api):
    """
    1. extracted = await process_reels_url(url)
       DownloadError → reply("⚠️ 無法下載此影片，請確認帳號是否公開")，return

    2. extracted.confidence < 0.5 → reply("🤔 無法辨識地點，請直接輸入地點名稱")，return

    3. lat, lng = await geocode(extracted.name, extracted.address_hint)
       GeocodingError → reply(f"找不到「{extracted.name}」的位置，請確認地點名稱")，return

    4. embed_text = f"{extracted.name}。{extracted.category}。{extracted.description}"
       embedding = await embed(embed_text)

    5. INSERT INTO places:
       user_session_id = session_id
       name            = extracted.name
       category        = extracted.category
       lat, lng        = lat, lng
       description     = extracted.description
       source_type     = 'reels_url'
       source_url      = url
       reels_caption   = extracted.caption
       embedding       = embedding
       hotel_legal_status = None（先不設定，等 M4 驗證後更新）

    6. 若 extracted.category == 'hotel':
       asyncio.create_task(_verify_hotel_async(place.id, extracted.name, lat, lng))

    7. reply(
         f"✅ 已加入「{extracted.name}」！\n"
         f"類型：{'🍽️ 美食' if category=='food' else '🏛️ 景點' if category=='attraction' else '🏨 住宿'}\n"
         f"📍 查看地圖：{WEB_APP_URL}?session={session_id}"
       )
    """

async def handle_plain_text(text: str, reply_token: str, session_id: str, line_api):
    """
    直接把 text 當地點名稱 geocode，寫入 places，source_type='text'
    """

async def handle_image(message_id: str, reply_token: str, session_id: str, line_api):
    """
    1. 用 line_api 下載圖片 binary
    2. extracted = await process_image_bytes(image_bytes)
    3. 後續同 handle_reels_url 步驟 2–7
    """

async def _verify_hotel_async(place_id: int, name: str, lat: float, lng: float):
    """
    Fire-and-forget task。
    呼叫 M4 的 match_hotel(name, lat, lng)。
    把結果寫回 places.hotel_legal_status 和 places.hotel_match_id。
    此函式不拋出例外（catch all，最多 log）。
    """
```

### M3.2 Geocoding Service

```python
# app/services/geocoding.py

async def geocode(name: str, address_hint: str = "") -> tuple[float, float]:
    """
    Google Maps Geocoding API

    query = f"{name} {address_hint} 台北市".strip()
    GET https://maps.googleapis.com/maps/api/geocode/json
        ?address={query}&language=zh-TW&region=tw&key={GOOGLE_MAPS_API_KEY}

    回傳 (lat, lng)
    results 為空 → 拋出 GeocodingError(f"找不到: {name}")
    """

class GeocodingError(Exception):
    pass
```

### M3.3 Embedder（M1 + M3 + M5 共用）

```python
# app/services/embedder.py

from openai import AsyncOpenAI

async def embed(text: str) -> list[float]:
    """
    model: text-embedding-3-small（1536 dim）
    單筆，供 M3 即時使用。
    """

async def embed_batch(texts: list[str]) -> list[list[float]]:
    """
    每 100 筆一批，供 M1 ingest 使用。
    每批 sleep(0.5)。
    """
```

### M3.4 Places Router

```python
# app/routers/places.py

# GET /places?session_id={str}
# SELECT * FROM places WHERE user_session_id = :session_id ORDER BY created_at DESC
# 回傳 Place[]（對應 M0.5 TypeScript 型別）

# POST /places
# body: { session_id, name, category, lat, lng, source_type, source_url? }
# INSERT + 計算 embedding
# 回傳 Place

# DELETE /places/{id}?session_id={str}
# 驗證 place.user_session_id == session_id（防止刪除別人的）
# DELETE，回傳 204
```

### M3.5 驗收條件

```
1. ngrok expose 8000，設定 Line Webhook URL
2. Line 傳一個公開 IG Reels URL
3. 30 秒內收到 reply（含地點名稱和地圖連結）
4. psql: SELECT name, category, lat, lng FROM places WHERE source_type='reels_url'
   → 有新一筆，lat/lng 在台北市範圍 (24.9–25.3, 121.4–121.8)
5. embedding IS NOT NULL
```

---

## M4: 旅宿守門員

> **依賴**: M0 (`legal_hotels` table schema)
> **被依賴**: M3 呼叫 `match_hotel()`；M6 呼叫 `GET /hotels/verify`

### M4 的職責邊界

- ✅ 建立並維護 `legal_hotels` table
- ✅ 提供 `match_hotel()` 函式（M3 import 使用）
- ✅ 提供 `GET /hotels/verify` endpoint（M6 使用）
- ❌ **不修改 `places` table**（M3 的 `_verify_hotel_async` 負責寫回結果）

### M4.1 Ingest Script

**Claude Code prompt for M4 ingest**:
> 實作 `scripts/ingest_hotels.py`，只使用 httpx + asyncpg，符合以下規格。

```python
# scripts/ingest_hotels.py
"""
執行方式: python scripts/ingest_hotels.py
需要環境變數: DATABASE_URL, GOOGLE_MAPS_API_KEY

資料來源:
1. 一般旅館名冊
   GET https://data.taipei/api/v1/dataset/4d7d0b46-2e90-4ee7-b000-c0f2f3a37651
       ?format=json&limit=1000&offset=0
   分頁直到 result.count 為 0

2. 旅遊網住宿資料
   GET https://data.taipei/api/v1/dataset/58093ba6-4c98-4148-b27a-50ad97d7afca
       ?format=json&limit=1000&offset=0

流程:
1. 取兩個來源的資料，合併 normalize（統一欄位名稱到 name, address, license_number）
2. 對 lat/lng 為 None 的資料，呼叫 Google Geocoding API 補齊
   每次 geocode 之間 sleep(0.1)
   geocode 失敗的 → lat/lng 留 None，仍然插入
3. INSERT INTO legal_hotels ON CONFLICT (license_number) DO UPDATE SET updated_at = NOW()
4. 印出統計
"""
```

### M4.2 比對服務

**Claude Code prompt for M4 matcher**:
> 實作 `app/services/hotel/matcher.py`，符合以下規格。

```python
# app/services/hotel/matcher.py

from rapidfuzz import fuzz, process
from dataclasses import dataclass, field

@dataclass
class MatchResult:
    status: str                # 'legal' | 'illegal' | 'unknown'
    match: dict | None         # matched hotel record
    alternatives: list = field(default_factory=list)
    score: float = 0.0

SCORE_THRESHOLD = 75           # 從 config 讀取，方便調整

async def match_hotel(name: str, lat: float, lng: float) -> MatchResult:
    """
    步驟:

    1. 從 legal_hotels 取 candidate pool:
       有座標: WHERE ABS(lat - :lat) < 0.01 AND ABS(lng - :lng) < 0.01
       （約 1km 範圍，0.01 度 ≈ 1.1km）
       無座標 fallback: SELECT ALL（約 1000 筆，仍可接受）

    2. rapidfuzz.process.extractOne(
           query=name,
           choices={h['id']: h['name'] for h in candidates},
           scorer=fuzz.token_sort_ratio,
           score_cutoff=SCORE_THRESHOLD
       )

    3. score >= SCORE_THRESHOLD:
           status = 'legal'，match = matched hotel record

       score < SCORE_THRESHOLD，有座標且在台北市:
           status = 'illegal'
           alternatives = 按座標距離排序，最近 3 間合法旅館
           （ORDER BY (lat-:lat)^2 + (lng-:lng)^2 ASC LIMIT 3）

       無座標或比對結果不確定:
           status = 'unknown'

    回傳 MatchResult
    """
```

### M4.3 Hotels Router

```python
# app/routers/hotels.py

# GET /hotels/verify?name={str}&lat={float}&lng={float}
# 呼叫 match_hotel(name, lat, lng)
# 回傳 HotelVerifyResult（對應 M0.5 TypeScript 型別）
```

### M4.4 驗收條件

```bash
python scripts/ingest_hotels.py
# SELECT COUNT(*) FROM legal_hotels → > 500

curl "localhost:8000/hotels/verify?name=台北君悅酒店&lat=25.033&lng=121.562"
# → { "status": "legal", "match": { "name": "君悅..." }, "alternatives": [] }

curl "localhost:8000/hotels/verify?name=阿貓阿狗非法民宿XYZ&lat=25.033&lng=121.562"
# → { "status": "illegal", "match": null, "alternatives": [{...}, {...}, {...}] }
```

---

## M5: RAG 推薦引擎

> **依賴**: M0 (DB), M1 (`attractions` table 已有資料), `services/embedder.py`
> **被依賴**: M6 呼叫 `POST /recommend`

### M5 的職責邊界

- ✅ 讀取 `attractions` 做向量搜尋
- ✅ 讀取 `places` 計算使用者偏好 centroid
- ✅ 呼叫 Claude 生成推薦理由（claude-haiku，速度優先）
- ❌ **不寫任何 table**
- ❌ 不知道 Line Bot 的存在

### M5.1 Recommender

**Claude Code prompt for M5**:
> 實作 `app/services/rag/recommender.py`，符合以下規格。

```python
# app/services/rag/recommender.py

import numpy as np
from anthropic import AsyncAnthropic

async def find_similar(
    session_id: str,
    category: str,
    limit: int = 5,
) -> list[dict]:
    """
    步驟:

    1. 取 session 的所有 places（含 embedding）
       若 len(places) == 0 → 回傳 []

    2. 計算 centroid:
       valid = [p.embedding for p in places if p.embedding is not None]
       centroid = np.mean(valid, axis=0).tolist()

    3. pgvector 向量搜尋:
       SELECT id, name, category, lat, lng, address, description, tags,
              embedding <=> :centroid AS distance
       FROM attractions
       WHERE category = :category
       ORDER BY distance ASC
       LIMIT :limit

    4. 並行生成 reason（asyncio.gather）:
       對每個 result，呼叫 Claude:
         model: claude-haiku-4-5-20251001（速度快）
         prompt: f"使用者收藏過：{place_names_joined}。
                  請用繁體中文一句話（20字以內）說明為什麼推薦「{result['name']}」。
                  只輸出那一句話，不要標點以外的任何文字。"

    5. 回傳:
       [
         {
           "attraction": { id, name, category, lat, lng, address, description, tags },
           "reason": "同樣是大稻埕一帶的老宅風格咖啡廳",
           "score": 0.234
         }
       ]
    """
```

### M5.2 Recommend Router

```python
# app/routers/recommend.py

# POST /recommend
# body: { "session_id": "abc", "category": "food", "limit": 5 }
# → find_similar(session_id, category, limit)
# → 回傳 RecommendResult[]
```

### M5.3 驗收條件

```bash
# 前置: M1 完成（attractions 有資料），M3 已用 Line 加入 >= 1 個 place

curl -X POST localhost:8000/recommend \
  -H "Content-Type: application/json" \
  -d '{"session_id": "your_session", "category": "food", "limit": 3}'

# 預期:
# - 回傳 3 個 attraction
# - 每個有 reason 字串（非空）
# - score < 0.5（cosine distance 越小越相似）
```

---

## M6: 前端地圖 UI

> **依賴**: M0 API Contract（HTTP only，不直接碰 DB）
> **完全獨立**: `NEXT_PUBLIC_USE_MOCK=true` 時不需要後端即可開發

### M6 的職責邊界

- ✅ 所有 UI 元件
- ✅ 呼叫 M0.4 定義的 HTTP API
- ❌ **不包含任何業務邏輯**（驗證、推薦計算等全在後端）
- ❌ **不直接操作 DB**

### M6.1 Mock Data（開發用）

```typescript
// frontend/src/lib/mock.ts
// NEXT_PUBLIC_USE_MOCK=true 時，api.ts 回傳這裡的資料

export const mockPlaces: Place[] = [
  {
    id: 1, user_session_id: "dev",
    name: "永康牛肉麵", category: "food",
    lat: 25.0329, lng: 121.5299,
    address: "台北市大安區永康街31號",
    description: "知名老店，半筋半肉麵是招牌",
    source_type: "reels_url",
    source_url: "https://www.instagram.com/reel/example",
    hotel_legal_status: null,
    created_at: "2025-01-01T10:00:00Z"
  },
  {
    id: 2, user_session_id: "dev",
    name: "台北君悅酒店", category: "hotel",
    lat: 25.0330, lng: 121.5654,
    address: "台北市信義區松壽路2號",
    description: "五星級旅館，信義區",
    source_type: "reels_url", source_url: null,
    hotel_legal_status: "legal",
    created_at: "2025-01-01T11:00:00Z"
  }
]

export const mockRecommendations: RecommendResult[] = [
  {
    attraction: {
      id: 101, name: "富錦街咖啡", category: "food",
      lat: 25.0559, lng: 121.5541,
      address: "台北市松山區富錦街",
      description: "老宅改建，手沖咖啡",
      tags: ["咖啡", "老宅"]
    },
    reason: "同樣是巷弄內的特色小店",
    score: 0.18
  }
]
```

### M6.2 元件規格

**Claude Code prompt for M6**:
> 實作 `frontend/src/` 下所有元件。先用 `lib/mock.ts`，`NEXT_PUBLIC_USE_MOCK=false` 後換成真實 API。
> 使用 Next.js 14 App Router + Tailwind CSS + Mapbox GL JS 3.x + SWR。

```typescript
// components/Map.tsx
/**
 * Props: {
 *   places: Place[]
 *   recommendations: RecommendResult[]
 *   selectedId: number | null
 *   onMarkerClick: (id: number, type: 'place' | 'recommendation') => void
 * }
 *
 * Mapbox 設定:
 *   center: [121.5654, 25.0330]，zoom: 12
 *   style: 'mapbox://styles/mapbox/light-v11'
 *
 * Marker 視覺:
 *   places (使用者收藏):         藍色圓形 #3B82F6，直徑 14px
 *   recommendations (AI 推薦):   金色圓形 #F59E0B，直徑 12px，帶 CSS pulse animation
 *   hotel_legal_status='legal':  綠色小盾牌 overlay
 *   hotel_legal_status='illegal': 紅色警告三角 overlay
 *
 *   點擊 marker → onMarkerClick()，不在地圖上顯示 popup（改在 Sidebar 顯示）
 *
 *   selectedId 對應的 marker 放大 1.5x
 */

// components/Sidebar.tsx
/**
 * 左側固定欄，寬 380px，三個 tab
 *
 * Tab 1「收藏」:
 *   PlaceCard list，按 created_at DESC
 *   底部固定:「✨ 一鍵生成行程」按鈕 → POST /itinerary/generate
 *
 * Tab 2「推薦」:
 *   Category filter pills: 全部 / 🍽️ 美食 / 🏛️ 景點 / 🏨 住宿
 *   RecommendCard list
 *   每個 card 有「+ 加入收藏」按鈕 → POST /places
 *
 * Tab 3「行程」:
 *   若無行程: 「先加入景點，再一鍵生成行程」
 *   有行程: ItineraryTimeline
 */

// components/PlaceCard.tsx
/**
 * Props: { place: Place, isSelected: boolean, onClick: () => void }
 * 顯示: category icon + 名稱 + 地址 (truncate) + source badge (Reels / 圖片 / 手動)
 * 若 category='hotel': 顯示 HotelBadge
 * isSelected: 左邊框高亮
 * onClick: 地圖 flyTo 該點，Sidebar scroll 到此 card
 */

// components/HotelBadge.tsx
/**
 * legal   → 綠底「🛡️ 合法旅宿」
 * illegal → 紅底「⚠️ 疑似非法日租」，hover tooltip: "可能有消防安全疑慮，建議選擇合法旅館"
 * unknown → 灰底「❓ 待確認」
 */

// hooks/usePlaces.ts
/**
 * SWR，revalidateOnFocus: true，refreshInterval: 5000
 * 每 5 秒 polling，讓 Line 傳入的 place 自動出現在地圖上
 *
 * const { places, isLoading, mutate } = usePlaces(sessionId)
 */

// hooks/useRecommendations.ts
/**
 * 只有 places.length >= 1 才 fetch（否則回傳 []）
 * category 來自 Sidebar 的 filter state
 *
 * const { recommendations } = useRecommendations(sessionId, category)
 */

// lib/api.ts
/**
 * SESSION_ID:
 *   const id = localStorage.getItem('wg_session_id') ?? crypto.randomUUID()
 *   localStorage.setItem('wg_session_id', id)
 *
 * USE_MOCK = process.env.NEXT_PUBLIC_USE_MOCK === 'true'
 *
 * 所有 fetch 加 BASE_URL = process.env.NEXT_PUBLIC_API_URL
 *
 * export const api = {
 *   getPlaces: (sessionId: string) => Place[]
 *   addPlace: (data: PlaceCreate) => Place
 *   deletePlace: (id: number, sessionId: string) => void
 *   verifyHotel: (name, lat, lng) => HotelVerifyResult
 *   getRecommendations: (sessionId, category, limit?) => RecommendResult[]
 *   generateItinerary: (sessionId, date, startTime?) => Itinerary
 * }
 */
```

### M6.3 驗收條件

```bash
NEXT_PUBLIC_USE_MOCK=true npm run dev

# 驗收:
# 1. localhost:3000 顯示台北地圖，有藍色和金色 marker
# 2. 側邊欄三個 tab 可切換
# 3. 點擊 marker → Sidebar 捲動到對應 card，marker 放大
# 4. hotel_legal_status='legal' 的 marker 有綠色盾牌 overlay
# 5. 切換「推薦」tab → filter pills 可切換 category
```

---

## M7: 行程生成（Phase 2）

> **依賴**: M0 (DB), M5 (find_similar)
> **MVP 優先度低**，Day 2 下午有餘力再實作

### M7.1 服務規格

```python
# app/services/itinerary/generator.py

async def generate(session_id: str, date: str, start_time: str = "09:00") -> dict:
    """
    1. 取 session 所有 places
    2. 取推薦 attractions（各 category 各 2 筆，呼叫 M5 的 find_similar）
    3. 合併約 5–10 個地點
    4. 取今日天氣（CWB API，失敗則 weather=None）
    5. 呼叫 claude-sonnet-4-20250514 生成行程

    System: 你是台北旅遊規劃師。只回傳 JSON，不要任何說明。

    User prompt 包含:
    - date, start_time
    - 天氣: description + temp（若有）
    - 地點清單: [{ name, category, lat, lng }]

    交通時間規則（寫進 prompt 讓 LLM 參考）:
    - 直線距離 < 500m → 步行 5 分鐘
    - 500m–2km → 步行 10–20 分鐘 or 計程車 5 分鐘
    - > 2km → MRT/計程車，每 1km ≈ 3 分鐘

    回傳 Itinerary（對應 M0.5 TypeScript 型別），存入 itineraries table
    """
```

---

## 實作順序（Hackathon 時程）

### Day 1 上午：底層到位（全員）

```bash
# 1. clone repo, docker-compose up, alembic upgrade head
# 2. 分工平行執行:
python scripts/ingest_hotels.py   # M4 負責，約 10 分鐘
python scripts/ingest_osm.py      # M1 負責，約 15 分鐘，背景跑著
# 3. M6 開發者: NEXT_PUBLIC_USE_MOCK=true npm run dev，把 UI 先跑起來
```

驗收：DB 有旅館資料，地圖在 localhost:3000 顯示

---

### Day 1 下午：核心模組

```
M2 負責者: 完整實作 + pytest tests/test_m2_media.py 全過
M4 負責者: match_hotel() + GET /hotels/verify + 驗收測試
M6 負責者: Sidebar tabs, HotelBadge, PlaceCard 完成
```

---

### Day 1 晚上：Line Bot 串接

```
M3 負責者: handle_reels_url 主線實作
  → ngrok expose 8000，設定 Line Webhook
  → 測試：Line 傳 IG Reels → DB 有 place
M5 負責者: find_similar() + POST /recommend
```

---

### Day 2 上午：全線串接

```
M3 + M4: hotel fire-and-forget 驗證，確認 HotelBadge 在前端顯示
M5 + M6: 前端接真實 /recommend API，換掉 mock
usePlaces polling: Line 傳入後地圖自動出現 marker
```

驗收：完整 E2E 流程跑通

---

### Day 2 下午：收尾 + Demo

```
全員: bug fix
選做: M7 行程生成
Demo 腳本演練（見下）
```

---

## Demo 腳本

**目標**: 評審 5 分鐘內看到核心價值

```
Step 1: Line 傳一個食物類 IG Reels URL
Step 2: 30 秒內收到 reply，顯示地點名稱
Step 3: 打開 Web App → 地圖自動出現藍色 marker
Step 4: 點擊 marker → 側邊欄顯示 PlaceCard
Step 5: 切換「推薦」tab → 金色 marker 出現相似食物景點
Step 6: Line 再傳一個旅館類 Reels
Step 7: PlaceCard 顯示綠色或紅色 HotelBadge
Step 8（選做）: 按「一鍵生成行程」→ ItineraryTimeline 顯示
```
