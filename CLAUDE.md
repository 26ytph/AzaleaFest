# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Source of truth

[taipei-wanderguard-tech-spec.md](taipei-wanderguard-tech-spec.md) is the **authoritative spec**. Every module's job description, file path, function signature, DB schema, HTTP contract, and TypeScript type lives there. When working on a single module, read only that module's section plus M0 — the spec is intentionally written so a Claude Code agent can be given one module's text without the others.

## Architecture: 7 modules with hard boundaries

The system is split into 7 modules (M0–M7) so 4 teammates can develop in parallel. Boundaries are enforced by:

1. **DB tables have a single owner.** Other modules may `SELECT` but never `ALTER` or write. Schema lives in M0.3.
   - `attractions` → M1 owns; M5 reads
   - `places` → M3 owns; M5/M6/M7 read
   - `legal_hotels` → M4 owns; M3 reads via `match_hotel()`
   - `itineraries` → M7 owns

2. **Cross-module calls go through one of two contracts:**
   - **HTTP** (M0.4): frontend ↔ backend, defined as `/places`, `/hotels/verify`, `/recommend`, `/itinerary/generate`
   - **Python imports** for backend-internal: M3 imports `process_reels_url`/`process_image_bytes` from M2, `match_hotel` from M4, `embed` from shared `services/embedder.py`. Signatures are frozen in the spec.

3. **M2 never writes DB.** Persistence is M3's job. M4 never writes `places` — M3's `_verify_hotel_async` writes the verification result back.

4. **M6 is fully decoupled.** With `NEXT_PUBLIC_USE_MOCK=true`, the frontend runs against `lib/mock.ts` and needs zero backend.

## Locked contract files (do not edit casually)

These are the boundaries between modules. Once filled per spec, changes require coordinated updates across multiple modules:

- `backend/alembic/versions/0001_initial.py` — DB schema (spec M0.3)
- `frontend/src/lib/types.ts` — frontend/backend type contract (spec M0.5)
- `.env.example` — env var keys (spec M0.2)
- `backend/requirements.txt` — pinned versions (spec M0.7)
- `backend/app/services/media/__init__.py` — `ExtractedContent` dataclass + `process_reels_url` / `process_image_bytes` signatures (spec M2.1)
- `backend/app/services/hotel/matcher.py` — `match_hotel()` signature + `MatchResult` (spec M4.2)
- `backend/app/services/embedder.py` — `embed()` / `embed_batch()` signatures (spec M3.3)

## Module ownership (4-person split)

| Owner | Modules | Notes |
|-------|---------|-------|
| A | M1 + M5 | OSM ingest + RAG (shares embedder) |
| B | M2 + M3 | Media pipeline + Line bot (M3 imports M2 directly) |
| C | M4 | Hotel data — independent vertical |
| D | M6 | Frontend — fully decoupled via mock |
| Phase 2 | M7 | Itinerary generation, picked up by whoever finishes first |

## Commands

```bash
# One-time setup (after M0 contracts are filled)
docker-compose up -d db redis
alembic upgrade head

# M1: populate attractions table (~10–15 min, run in background on Day 1)
python backend/scripts/ingest_osm.py

# M4: populate legal_hotels table (~10 min)
python backend/scripts/ingest_hotels.py

# Backend dev
cd backend && uvicorn app.main:app --reload

# Frontend dev (mock mode — no backend needed)
cd frontend && NEXT_PUBLIC_USE_MOCK=true npm run dev

# Frontend dev (live backend)
cd frontend && NEXT_PUBLIC_USE_MOCK=false npm run dev

# Tests (per-module)
pytest backend/tests/test_m2_media.py -v
pytest backend/tests/test_m4_hotel.py -v
pytest backend/tests/test_m5_rag.py -v

# Single test
pytest backend/tests/test_m2_media.py::test_extract_keyframe_valid -v

# Line webhook local dev
ngrok http 8000   # then set Line webhook URL to https://<id>.ngrok.io/webhook/line

# DB migrations (only M0 maintainer)
cd backend && alembic revision --autogenerate -m "add xxx column"
cd backend && alembic upgrade head
```

## Current state

The repo is currently a scaffold — directories and empty files match spec M0.1, but no implementation exists yet. The contract files listed above must be filled per spec **before** module owners start their work; everything else can be filled lazily.

## Working on a single module

When asked to implement a module, the spec section for that module is self-contained:

- Read **only** M0 + the target module's section.
- Don't touch tables you don't own. If you need a new column, update spec M0.3 first and let the M0 maintainer create the migration.
- Don't add cross-module imports beyond what the spec lists. If you need something from another module, either it should be exposed via HTTP (M0.4) or a frozen Python signature.
- The "Claude Code prompt for Mx" callouts in the spec are designed to be pasted directly to an agent working on that module.
