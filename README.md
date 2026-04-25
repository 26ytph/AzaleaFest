# AzaleaFest — Taipei WanderGuard

Taipei 旅遊規劃 + 旅宿合法性守門員。架構分 7 個模組（M0–M7）並行開發；本 README 聚焦在
**讓你 docker 起服務後直接用 M1 景點庫 + M5 推薦 endpoint**，不必在本機重跑十幾分鐘的 embedding。

完整模組設計請看 [taipei-wanderguard-tech-spec.md](taipei-wanderguard-tech-spec.md)；
M1 + M5 的內部設計筆記在 [M1.md](M1.md)。

---

## 用 docker 起服務（接 M1 景點庫 + M5 推薦）

### 一次設定

```bash
git clone <this-repo>
cd AzaleaFest
cp .env.example .env
# 編輯 .env，至少填這幾項：
#   GEMINI_API_KEY        — M5 reason 用（沒填 /recommend 仍會跑，理由會 fallback 預設句）
#   GOOGLE_MAPS_API_KEY   — 如果你也要跑 M3 / M4 才需要
#   LINE_CHANNEL_*        — 如果你要跑 Line Bot 才需要
```

### 啟動（自動拉預算好的景點 embedding）

```bash
docker compose up -d
```

第一次啟動時 backend container 會：
1. `alembic upgrade head` — 建表（含雙 embedding column）
2. `scripts/bootstrap_attractions.py` — 從 Hugging Face dataset
   `azaleafest/wanderguard-attractions` 下載 `attractions.dump`，`pg_restore` 回 DB
3. `CREATE INDEX` 建 ivfflat（pgvector ANN）+ `ANALYZE`
4. `uvicorn` 啟 FastAPI

第一次拉 dump 約 30-60 秒（壓縮後 30-50 MB）。之後重啟 < 5 秒。

> Embedding model（bge-m3 + mpnet-base，共 ~3 GB）在第一次有 endpoint 命中需要 embed 時才下載，
> 透過 `./.cache/huggingface` volume mount 到 host，重啟不重抓。

### 確認服務正常

```bash
curl localhost:8000/health
# {"status":"ok"}

# 看景點 table 有資料
docker compose exec db psql -U user -d wanderguard \
  -c "SELECT category, COUNT(*) FROM attractions GROUP BY category;"
# food:       約 5000+
# attraction: 約 4000+

# 看 embedding 都填了
docker compose exec db psql -U user -d wanderguard -c "
  SELECT COUNT(*) FILTER (WHERE embedding_bgem3 IS NOT NULL) AS bgem3,
         COUNT(*) FILTER (WHERE embedding_mpnet IS NOT NULL) AS mpnet
  FROM attractions;"
# 兩個數字應該都接近總數（≥ 99%）
```

---

## API: `POST /recommend`（M5）

雙 model 檢索 + RRF 合併 + Gemini 推薦理由。詳細流程見 M1.md §13。

### 前置條件

`places` 表至少有 1 筆有 embedding 的資料（user 透過 Line Bot 加入過任何地點，
或用 `POST /places` 手動加）。

### 範例

```bash
curl -X POST http://localhost:8000/recommend \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "demo-session",
    "category": "food",
    "limit": 3
  }'
```

回傳格式（對齊 `frontend/src/lib/types.ts:RecommendResult`）：

```json
[
  {
    "attraction": {
      "id": 4231,
      "name": "明月湯包",
      "category": "food",
      "lat": 25.0421,
      "lng": 121.5634,
      "address": "台北市基隆路二段 162-4 號",
      "description": "...",
      "tags": ["restaurant", "chinese"]
    },
    "reason": "同樣是巷弄裡的家常台菜",
    "score": 0.234
  },
  ...
]
```

`category` 必須是 `"hotel" | "food" | "attraction"`。`limit` 預設 5，上限 20。
`score` 是兩個 model 的 cosine distance 平均，越小越相似。

---

## 進階：自己重新 ingest 景點

只有「換了 embedder model」或「想加新資料來源」時才需要這步。
一般使用者直接用 HF 拉的 dump 即可。

```bash
# 先確保你有 GPU（不是必須，CPU 也能跑，但 4-6 小時 vs 30-60 分鐘）
docker compose up -d db
docker compose run --rm backend alembic upgrade head

# 跑 ingest（OSM Overpass + 觀光署 + Wikidata 三個來源 → 雙 embedding）
docker compose run --rm backend python scripts/ingest_osm.py

# 跑完後 dump
docker compose run --rm backend python scripts/dump_attractions.py
# → backend/data/dumps/attractions.dump

# 上傳到 HF（用新版 hf CLI；huggingface-cli 已 deprecated）
hf auth login   # 一次就好
hf upload \
  azaleafest/wanderguard-attractions \
  backend/data/dumps/attractions.dump attractions.dump \
  --repo-type=dataset
```

### 跳過 bootstrap

GPU 端首次自己 ingest 時不希望 backend 幫你拉舊 dump，加：

```bash
SKIP_BOOTSTRAP=1 docker compose up
```

或者乾脆用 `docker compose run --rm backend python scripts/ingest_osm.py` —— 這條指令的
args 會 override compose 的 `command`，bootstrap 自然跳過。

---

## 開發 frontend 不依賴後端

```bash
cd frontend
NEXT_PUBLIC_USE_MOCK=true npm run dev
```

走 `lib/mock.ts`，零後端 dependency。

---

## Troubleshooting

**Q: backend 啟動卡在 bootstrap，下載失敗（401 / 403）**
A: dataset 可能是 private。到 `https://huggingface.co/settings/tokens` 拿 read token，
   寫進 `.env` 的 `HF_TOKEN=hf_...`。或請 dataset owner 把 visibility 改 public。

**Q: bootstrap 完全沒網路 / dataset 還沒人傳**
A: 設 `SKIP_BOOTSTRAP=1` 跳過，再用 `docker compose run --rm backend python scripts/ingest_osm.py`
   自己 ingest（CPU 約 4-6 小時，GPU 約 30-60 分鐘）。

**Q: `/recommend` 回 `[]`**
A: 該 `session_id` 在 `places` 表沒任何 row，或所有 row 的 embedding 都是 NULL。
   先用 `POST /places` 加幾筆。

**Q: `/recommend` 的 reason 都是 "依你最近收藏的風格挑的"**
A: `GEMINI_API_KEY` 沒設、quota 用完、或 model 暫時 503。endpoint 不會 500，
   reason 會走 fallback 字串。

**Q: 重新跑 alembic 失敗：column "embedding" already exists**
A: 之前在 0001 schema 跑過 ingest，現在要套 0002。先：
   `docker compose down -v`（清 pgdata volume）→ `docker compose up`。
   注意這會**清掉所有 places / itineraries 資料**。
