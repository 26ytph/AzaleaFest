"""One-time backfill of locale-specific attraction names.

CLI:
    python scripts/translate_attractions.py --lang en
    python scripts/translate_attractions.py --lang ja
    python scripts/translate_attractions.py --lang ko
    python scripts/translate_attractions.py --lang zh-CN

Idempotent: only updates rows where the target column IS NULL. Re-runs
pick up where a previous run was interrupted.

Strategies:
  - zh-CN: opencc Traditional → Simplified (mechanical, ~30 sec for 16k rows)
  - en/ja/ko: gemini-2.5-flash-lite, batch of 50 names per request, JSON output
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Load .env from project root so DATABASE_URL / GEMINI_API_KEY are available
ENV_FILE = PROJECT_ROOT / ".env"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from sqlalchemy import select, update  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.attraction import Attraction  # noqa: E402

# lang code → DB column name
LANG_COLUMN = {
    "en": "name_en",
    "ja": "name_ja",
    "ko": "name_ko",
    "zh-CN": "name_zh_cn",
}

# lang code → human-readable target language used in Gemini prompt
LANG_PROMPT_NAME = {
    "en": "English",
    "ja": "Japanese (日本語)",
    "ko": "Korean (한국어)",
}

GEMINI_MODEL = "gemini-2.5-flash-lite"
GEMINI_BATCH = 50
GEMINI_SLEEP = 0.4  # seconds between batches; lite model has high RPM


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

async def fetch_pending(lang: str) -> list[tuple[int, str]]:
    """Return rows where target column is NULL, as (id, name)."""
    column = getattr(Attraction, LANG_COLUMN[lang])
    async with SessionLocal() as session:
        rows = await session.execute(
            select(Attraction.id, Attraction.name).where(column.is_(None))
        )
        return [(r[0], r[1]) for r in rows.all()]


async def write_translations(lang: str, items: list[tuple[int, str]]) -> int:
    """Bulk update; items = [(id, translated_name), ...]. Returns rows updated."""
    if not items:
        return 0
    column_name = LANG_COLUMN[lang]
    async with SessionLocal() as session:
        for aid, name in items:
            await session.execute(
                update(Attraction)
                .where(Attraction.id == aid)
                .values({column_name: name})
            )
        await session.commit()
        return len(items)


# ---------------------------------------------------------------------------
# zh-CN: opencc mechanical conversion
# ---------------------------------------------------------------------------

def convert_zh_cn(names: list[str]) -> list[str]:
    from opencc import OpenCC
    cc = OpenCC("t2s")
    return [cc.convert(n) for n in names]


async def run_zh_cn() -> None:
    pending = await fetch_pending("zh-CN")
    if not pending:
        print("[zh-CN] all rows already populated", flush=True)
        return
    print(f"[zh-CN] converting {len(pending)} rows via opencc t2s", flush=True)
    converted = convert_zh_cn([n for _, n in pending])
    pairs = list(zip([aid for aid, _ in pending], converted))
    # write in chunks of 500 to keep one transaction reasonably small
    written = 0
    for i in range(0, len(pairs), 500):
        chunk = pairs[i : i + 500]
        written += await write_translations("zh-CN", chunk)
        print(f"[zh-CN] wrote {written}/{len(pairs)}", flush=True)


# ---------------------------------------------------------------------------
# en / ja / ko: Gemini batch translation
# ---------------------------------------------------------------------------

_PROMPT = """You are a professional Taipei-tourism translator.

Translate each Chinese attraction/restaurant/shop name below into {target_lang}.
Rules:
1. Keep proper nouns and brand names natural in {target_lang} (transliterate
   if no established translation exists).
2. Output ONLY a JSON array of strings, same length and order as the input.
3. Do not add explanations, markdown, or extra text.

Input (JSON array of {n} items):
{input_json}
"""


async def gemini_translate_batch(
    client, target_lang: str, names: list[str]
) -> list[str | None]:
    """Translate a batch of names. Returns list aligned with names; None on
    parse failure for that batch (caller will skip)."""
    from google.genai import types

    prompt = _PROMPT.format(
        target_lang=target_lang,
        n=len(names),
        input_json=json.dumps(names, ensure_ascii=False),
    )
    try:
        resp = await client.aio.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2,
                max_output_tokens=4096,
            ),
        )
        text = (resp.text or "").strip()
        parsed = json.loads(text)
        if not isinstance(parsed, list) or len(parsed) != len(names):
            return [None] * len(names)
        return [str(x) if x is not None else None for x in parsed]
    except Exception as e:
        print(f"  ! batch failed: {type(e).__name__}: {e}", flush=True)
        return [None] * len(names)


async def run_gemini(lang: str) -> None:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        sys.exit(f"[{lang}] GEMINI_API_KEY not set")
    from google import genai

    client = genai.Client(api_key=api_key)
    target_lang = LANG_PROMPT_NAME[lang]

    pending = await fetch_pending(lang)
    if not pending:
        print(f"[{lang}] all rows already populated", flush=True)
        return

    total = len(pending)
    print(
        f"[{lang}] translating {total} rows via Gemini ({GEMINI_MODEL}, "
        f"batch={GEMINI_BATCH}, target={target_lang})",
        flush=True,
    )

    written = 0
    failed = 0
    started = time.time()
    for i in range(0, total, GEMINI_BATCH):
        chunk = pending[i : i + GEMINI_BATCH]
        names = [n for _, n in chunk]
        translated = await gemini_translate_batch(client, target_lang, names)
        good = [
            (aid, t)
            for (aid, _), t in zip(chunk, translated)
            if t is not None and t.strip()
        ]
        written += await write_translations(lang, good)
        failed += len(chunk) - len(good)
        elapsed = time.time() - started
        eta = (elapsed / max(written, 1)) * (total - written - failed)
        print(
            f"[{lang}] {written}/{total} written, {failed} skipped "
            f"(elapsed {elapsed:.0f}s, eta {eta:.0f}s)",
            flush=True,
        )
        await asyncio.sleep(GEMINI_SLEEP)

    print(f"[{lang}] done: {written} written, {failed} skipped", flush=True)


# ---------------------------------------------------------------------------
# entrypoint
# ---------------------------------------------------------------------------

async def main_async(lang: str) -> None:
    if lang == "zh-CN":
        await run_zh_cn()
    else:
        await run_gemini(lang)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--lang", required=True, choices=list(LANG_COLUMN.keys()))
    args = p.parse_args()
    asyncio.run(main_async(args.lang))


if __name__ == "__main__":
    main()
