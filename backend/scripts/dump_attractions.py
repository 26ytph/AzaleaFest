"""把 `attractions` 整張表（含預先算好的雙 embedding）dump 成 pg_dump 自定格式檔.

執行方式（GPU 端，已跑完 ingest_osm.py 後）:
    docker compose run --rm backend python scripts/dump_attractions.py

產出: backend/data/dumps/attractions.dump（pg_dump --data-only -Fc 二進位，~30-50MB）

接下來上傳到 Hugging Face dataset（用新版 `hf` CLI；舊 `huggingface-cli` 已 deprecated）:
    hf auth login   # 一次就好
    hf upload \\
        azaleafest/wanderguard-attractions \\
        backend/data/dumps/attractions.dump \\
        attractions.dump \\
        --repo-type=dataset

之後其他人 `docker compose up` 啟動時，bootstrap_attractions.py 會自動拉這個 dump
還原到他們本機的 attractions table，他們不必重跑 ingest。

設計細節見 M1.md §15。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_DUMP_DIR = Path(__file__).resolve().parent.parent / "data" / "dumps"
_DUMP_FILE = _DUMP_DIR / "attractions.dump"


def _pg_dsn() -> str:
    """SQLAlchemy URL → libpq URL（剝掉 +asyncpg / +psycopg2 driver）。"""
    raw = os.environ.get("DATABASE_URL")
    if not raw:
        sys.exit("DATABASE_URL not set")
    return raw.replace("+asyncpg", "").replace("+psycopg2", "")


def main() -> None:
    _DUMP_DIR.mkdir(parents=True, exist_ok=True)
    dsn = _pg_dsn()

    cmd = [
        "pg_dump",
        "--data-only",
        "--table=attractions",
        "--format=custom",     # binary, compressed
        "--file", str(_DUMP_FILE),
        dsn,
    ]
    print(f"[dump] {' '.join(cmd[:-1])} <DSN>", flush=True)
    subprocess.run(cmd, check=True)

    size_mb = _DUMP_FILE.stat().st_size / (1024 * 1024)
    print(f"[dump] wrote {_DUMP_FILE} ({size_mb:.1f} MB)", flush=True)
    print(
        "\nNext step (host shell, 新版 hf CLI):\n"
        "  hf auth login\n"
        "  hf upload azaleafest/wanderguard-attractions \\\n"
        f"    {_DUMP_FILE} attractions.dump --repo-type=dataset\n",
        flush=True,
    )


if __name__ == "__main__":
    main()
