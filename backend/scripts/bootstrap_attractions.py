"""容器啟動時自動跑（由 scripts/start.sh 呼叫）.

職責:
  1. 偵測 `attractions` 是否為空
  2. 若是 → 從 Hugging Face dataset 拉預算好的 dump → pg_restore
  3. 還原後建 ivfflat index（pgvector 要在已有資料時建）+ ANALYZE
  4. 印 sanity check

若 `attractions` 已有資料 → 直接 return（idempotent）。

env 控制:
  HF_DATASET_REPO   預設 "azaleafest/wanderguard-attractions"
  HF_DATASET_FILE   預設 "attractions.dump"
  SKIP_BOOTSTRAP    "1" → 跳過整個流程（用於開發 / GPU 端首次 ingest）

設計細節見 M1.md §15。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_DEFAULT_REPO = "azaleafest/wanderguard-attractions"
_DEFAULT_FILE = "attractions.dump"

_INDEX_SQLS = [
    "CREATE INDEX IF NOT EXISTS attractions_embedding_bgem3_ivfflat "
    "ON attractions USING ivfflat (embedding_bgem3 vector_cosine_ops) "
    "WITH (lists = 100)",
    "CREATE INDEX IF NOT EXISTS attractions_embedding_mpnet_ivfflat "
    "ON attractions USING ivfflat (embedding_mpnet vector_cosine_ops) "
    "WITH (lists = 100)",
    "ANALYZE attractions",
]


def _libpq_dsn() -> str:
    raw = os.environ.get("DATABASE_URL")
    if not raw:
        sys.exit("[bootstrap] DATABASE_URL not set")
    return raw.replace("+asyncpg", "").replace("+psycopg2", "")


def _connect():
    """psycopg2 sync connection — 啟動時用 sync 比 async 簡單。"""
    import psycopg2
    return psycopg2.connect(_libpq_dsn())


def _count_attractions() -> int:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM attractions")
        return cur.fetchone()[0]


def _count_embedded() -> int:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM attractions "
            "WHERE embedding_bgem3 IS NOT NULL AND embedding_mpnet IS NOT NULL"
        )
        return cur.fetchone()[0]


def _download_dump() -> Path:
    """從 HF dataset 下載到 /tmp。需要 huggingface_hub package。"""
    repo = os.environ.get("HF_DATASET_REPO", _DEFAULT_REPO)
    fname = os.environ.get("HF_DATASET_FILE", _DEFAULT_FILE)
    print(f"[bootstrap] downloading {fname} from HF dataset {repo}", flush=True)
    from huggingface_hub import hf_hub_download
    local_path = hf_hub_download(
        repo_id=repo, filename=fname, repo_type="dataset",
        cache_dir="/tmp/hf-bootstrap-cache",
    )
    return Path(local_path)


def _restore(dump_path: Path) -> None:
    """pg_restore --data-only —— schema 已經被 alembic 建好。"""
    cmd = [
        "pg_restore",
        "--data-only",
        "--no-owner",
        "--no-privileges",
        "--dbname", _libpq_dsn(),
        str(dump_path),
    ]
    print(f"[bootstrap] {' '.join(cmd[:-1])} {dump_path.name}", flush=True)
    subprocess.run(cmd, check=True)


def _post_restore_sql() -> None:
    """建 ivfflat index 跟 ANALYZE。"""
    print("[bootstrap] creating ivfflat indexes + ANALYZE", flush=True)
    with _connect() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            for sql in _INDEX_SQLS:
                cur.execute(sql)


def main() -> int:
    if os.environ.get("SKIP_BOOTSTRAP") == "1":
        print("[bootstrap] SKIP_BOOTSTRAP=1, skipping", flush=True)
        return 0

    try:
        existing = _count_attractions()
    except Exception as e:
        # 第一次啟動 alembic 還沒跑完？理論上不會發生，因為 start.sh 順序保證
        print(f"[bootstrap] cannot read attractions table ({e}); skipping", flush=True)
        return 0

    if existing > 0:
        embedded = _count_embedded()
        print(
            f"[bootstrap] attractions already populated "
            f"({existing} rows, {embedded} fully embedded); skip",
            flush=True,
        )
        return 0

    print(f"[bootstrap] attractions empty, restoring from HF dataset", flush=True)
    try:
        dump_path = _download_dump()
    except Exception as e:
        # 沒網路 / dump 還沒上傳 → 不要擋 backend 啟動，讓 user 自己跑 ingest
        print(
            f"[bootstrap] dump download failed ({type(e).__name__}: {e}); "
            f"backend will start with empty attractions. "
            f"Run scripts/ingest_osm.py to populate manually.",
            flush=True,
        )
        return 0

    _restore(dump_path)
    _post_restore_sql()

    total = _count_attractions()
    embedded = _count_embedded()
    print(
        f"[bootstrap] restore done | {total} rows | "
        f"{embedded} with both embeddings | indexes ready",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
