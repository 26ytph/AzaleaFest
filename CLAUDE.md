# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Sources of truth (read these before editing)

1. [taipei-wanderguard-tech-spec.md](taipei-wanderguard-tech-spec.md) — **authoritative cross-module spec.** Module job descriptions, file paths, frozen function signatures, DB schema, HTTP contracts, and the TypeScript types live here. Each module's section is self-contained: when working on one module, read only M0 + that module's section.
2. [M1.md](M1.md) — internal design notes for M1 (OSM ingest) + M5 (RAG). Spec describes a single Gemini embedder; **M1.md §9 supersedes that** with a dual local embedder (bge-m3 + mpnet) + RRF retrieval, and §11–§15 cover the dual-embedding migration, dump/HF-bootstrap flow, and the `/recommend` pipeline that the code actually implements. If the spec and M1.md disagree on M1/M5 internals, M1.md wins.
3. [README.md](README.md) — the user-facing docker-compose quickstart (HF dump bootstrap, `/recommend` example, troubleshooting).

## Architecture: 7 modules with hard boundaries

Split into 7 modules (M0–M7) so 4 teammates can develop in parallel. Boundaries are enforced by:

1. **DB tables have a single owner.** Other modules may `SELECT` but never `ALTER` or write.
   - `attractions` → M1 owns; M5/M7 read
   - `places` → M3 owns; M5/M6/M7 read
   - `legal_hotels` → M4 owns; M3 reads via `match_hotel()`
   - `itineraries` → M7 owns

2. **Cross-module calls go through one of two contracts:**
   - **HTTP** (M0.4): frontend ↔ backend, defined as `/places`, `/hotels/verify`, `/recommend`, `/itinerary/generate`, `/webhook/line`
   - **Python imports** for backend-internal: M3 imports `process_reels_url`/`process_image_bytes` from M2 (`app.services.media`), `match_hotel` from M4 (`app.services.hotel.matcher`), and the embedder funcs from `app.services.embedder`. Signatures are frozen.

3. **M2 never writes DB.** Persistence is M3's job. M4 never writes `places` — M3's hotel handler writes the verification result back.

4. **M6 is fully decoupled.** With `NEXT_PUBLIC_USE_MOCK=true`, the frontend runs against `lib/mock.ts` and needs zero backend.

## Locked contract files (do not edit casually)

These are the boundaries between modules; changes require coordinated updates across multiple modules:

- `backend/alembic/versions/0001_initial.py` — base DB schema (spec M0.3). Schema deltas land as numbered follow-ups (`0002_dual_embeddings.py`, `0003_name_translations.py`).
- `frontend/src/lib/types.ts` — frontend/backend type contract (spec M0.5). Pydantic response models (e.g. `PlaceOut`, `RecommendResult`, `AttractionOut`) must stay aligned with this file.
- `.env.example` — env var keys (spec M0.2)
- `backend/requirements.txt` — pinned versions
- `backend/app/services/media/__init__.py` — `ExtractedContent` dataclass + `process_reels_url` / `process_image_bytes` signatures (spec M2.1)
- `backend/app/services/hotel/matcher.py` — `match_hotel()` signature + `MatchResult` (spec M4.2)
- `backend/app/services/embedder.py` — `embed_bgem3` / `embed_mpnet` / `embed_batch_bgem3` / `embed_batch_mpnet` for the dual-embedder flow, plus the spec-frozen `embed` / `embed_batch` aliases (default to bge-m3) for back-compat callers.

## Embedder architecture (the easy thing to get wrong)

The spec was written for a single Gemini embedding column. **The actual code uses two local sentence-transformer models in parallel** (`BAAI/bge-m3` → 1024 dim, `paraphrase-multilingual-mpnet-base-v2` → 768 dim). Both `attractions` and `places` have `embedding_bgem3` and `embedding_mpnet` columns. Reasons (M1.md §9–§10):

- Bge-m3 nails Chinese long semantic, mpnet nails place-name/brand short tokens; RRF fuses both.
- Local models avoid Gemini free-tier RPM caps that broke ingest at ~15k rows.
- GPU autodetect (`torch.cuda.is_available()`); HF cache is bind-mounted from `./.cache/huggingface` so model weights survive container rebuilds.

`/recommend` does **zero embedding work at query time** — `places.embedding_*` is filled at insert time inside `POST /places`, and the user's centroid is `numpy.mean(embeddings)`. This is why the endpoint is < 1s on CPU even though both models would be ~slow to invoke.

## How attractions get populated (do not run a fresh ingest unless you mean it)

Default flow for teammates: `docker compose up` runs `backend/scripts/start.sh`, which does `alembic upgrade head` → `scripts/bootstrap_attractions.py`. The bootstrap script:
1. Skips if `attractions` already has rows.
2. Otherwise downloads `attractions.dump` from HF dataset `azaleafest/wanderguard-attractions` and `pg_restore`s it (~30–60s, dump is 30–50 MB).
3. Creates ivfflat indexes (must be built **after** data exists for good clustering) and `ANALYZE`s.

`SKIP_BOOTSTRAP=1` skips step 2–3 (use this when you actually want a fresh ingest, or if HF is unreachable). `docker compose run --rm backend python ...` overrides the entrypoint, so it also skips bootstrap.

A fresh ingest (`scripts/ingest_osm.py`) is **4–6 hours on CPU**, 30–60 min on GPU. Only do it when changing embedders or adding sources. After ingest, `scripts/dump_attractions.py` produces a new dump for HF upload (`hf upload …`, see README §「進階：自己重新 ingest」).

## Module ownership

| Owner | Modules | Notes |
|-------|---------|-------|
| A | M1 + M5 | OSM ingest + RAG (shares embedder) |
| B | M2 + M3 | Media pipeline + Line bot (M3 imports M2 directly) |
| C | M4 | Hotel data — independent vertical |
| D | M6 | Frontend — fully decoupled via mock |
| Phase 2 | M7 | Itinerary generation, picked up by whoever finishes first |

## Commands

```bash
# Standard local dev: bring up DB + backend (auto migrations + auto HF bootstrap of attractions) + redis + frontend
docker compose up -d

# Skip the HF bootstrap (e.g. you want to ingest from scratch yourself)
SKIP_BOOTSTRAP=1 docker compose up

# Run a one-shot script in the backend image (overrides entrypoint, so bootstrap is skipped)
docker compose run --rm backend python scripts/ingest_osm.py
docker compose run --rm backend python scripts/ingest_hotels.py
docker compose run --rm backend python scripts/translate_attractions.py --lang ja

# Backend dev outside docker (DB still in docker)
cd backend && uvicorn app.main:app --reload

# Frontend (mock mode — no backend needed)
cd frontend && NEXT_PUBLIC_USE_MOCK=true npm run dev
# Frontend (live backend)
cd frontend && NEXT_PUBLIC_USE_MOCK=false npm run dev
cd frontend && npm run typecheck
cd frontend && npm run lint

# Tests (pytest is configured asyncio_mode=auto in backend/pytest.ini)
cd backend && pytest                                       # all
cd backend && pytest tests/test_m5_rag.py -v               # one file
cd backend && pytest tests/test_m4_hotel.py::test_xxx -v   # one test

# Sanity-check populated data
docker compose exec db psql -U user -d wanderguard -c \
  "SELECT category, COUNT(*) FROM attractions GROUP BY category;"
docker compose exec db psql -U user -d wanderguard -c \
  "SELECT COUNT(*) FILTER (WHERE embedding_bgem3 IS NOT NULL) AS bgem3,
          COUNT(*) FILTER (WHERE embedding_mpnet  IS NOT NULL) AS mpnet
   FROM attractions;"

# DB migrations (M0 maintainer only)
cd backend && alembic revision --autogenerate -m "add xxx column"
cd backend && alembic upgrade head

# Line webhook local dev
ngrok http 8000   # set Line webhook URL to https://<id>.ngrok.io/webhook/line
```

## Working on a single module

- Read **only** M0 + the target module's section of the spec. For M1/M5 also read M1.md.
- Don't touch tables you don't own. If you need a new column, add a numbered alembic migration (e.g. `0004_*.py`) and update spec M0.3.
- Don't add cross-module imports beyond what the spec lists. New cross-module needs go through HTTP (M0.4) or a frozen Python signature.
- Pydantic response models in routers must stay aligned with `frontend/src/lib/types.ts`. The translation columns (`name_en/ja/ko/zh_cn`) are exposed through `/recommend` — frontend picks by locale and falls back to `name`.
- The "Claude Code prompt for Mx" callouts in the spec are designed to be pasted directly to an agent working on that module.

## Quirks worth knowing

- `backend/scripts/start.sh` hot-patches `line-bot-sdk` to 3.14.5 on container start because old built images had 3.14.0 (which has a syntax bug). Once the image is rebuilt this can be removed.
- `docker-compose.override.yml` mounts `./backend → /app` for live reloads and bind-mounts `~/.cache/huggingface` so the ~3 GB embedder weights persist across container rebuilds.
- `M5._search_attractions` issues `SET LOCAL ivfflat.probes = 50` per query — the default of 1 was missing the requested category when the user's centroid landed in another category's cluster.
- `match_hotel()` runs **two-stage** matching (1km window with cutoff 75, then global with cutoff 90) — geocoding errors of 1+ km from vague queries like `福華大飯店` were sliding the real match outside the window.
- `translate_attractions.py` does zh-TW→zh-CN via `opencc` (mechanical, ~30s for 16k rows) but uses `gemini-2.5-flash-lite` for en/ja/ko in batches of 50. It's idempotent: only fills NULL columns.
