"""dual embeddings: bge-m3 (1024) + mpnet (768)

Revision ID: 0002_dual_embeddings
Revises: 0001_initial
Create Date: 2026-04-25

設計見 M1.md §11。

ivfflat index 故意不在 migration 內建立 — pgvector 文件明示要在已有資料時
建效果才好。索引交給 scripts/ingest_osm.py phase 2 結束時 CREATE IF NOT EXISTS；
pg_dump 會帶上索引定義，隊友 pg_restore 自動拿到。

places 表為 per-session 小表，先不建 ivfflat（順序掃即可）。
"""
from alembic import op


revision = "0002_dual_embeddings"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- attractions ----
    op.execute("DROP INDEX IF EXISTS attractions_embedding_ivfflat")
    op.execute("ALTER TABLE attractions DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE attractions ADD COLUMN embedding_bgem3 vector(1024)")
    op.execute("ALTER TABLE attractions ADD COLUMN embedding_mpnet vector(768)")

    # ---- places ----
    op.execute("DROP INDEX IF EXISTS places_embedding_ivfflat")
    op.execute("ALTER TABLE places DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE places ADD COLUMN embedding_bgem3 vector(1024)")
    op.execute("ALTER TABLE places ADD COLUMN embedding_mpnet vector(768)")


def downgrade() -> None:
    op.execute("ALTER TABLE places DROP COLUMN IF EXISTS embedding_mpnet")
    op.execute("ALTER TABLE places DROP COLUMN IF EXISTS embedding_bgem3")
    op.execute("ALTER TABLE places ADD COLUMN embedding vector(1536)")
    op.execute(
        "CREATE INDEX places_embedding_ivfflat "
        "ON places USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )

    op.execute("ALTER TABLE attractions DROP COLUMN IF EXISTS embedding_mpnet")
    op.execute("ALTER TABLE attractions DROP COLUMN IF EXISTS embedding_bgem3")
    op.execute("ALTER TABLE attractions ADD COLUMN embedding vector(1536)")
    op.execute(
        "CREATE INDEX attractions_embedding_ivfflat "
        "ON attractions USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )
