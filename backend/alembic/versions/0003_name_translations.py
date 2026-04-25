"""attraction name translations: name_ja, name_ko, name_zh_cn

Revision ID: 0003_name_translations
Revises: 0002_dual_embeddings
Create Date: 2026-04-26

`name_en` already exists from 0001_initial; this migration only adds the three
new locale-specific columns. Backfill is done by scripts/translate_attractions.py
(opencc for zh-CN, Gemini batch for ja/ko/en).
"""
from alembic import op


revision = "0003_name_translations"
down_revision = "0002_dual_embeddings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE attractions ADD COLUMN IF NOT EXISTS name_ja TEXT")
    op.execute("ALTER TABLE attractions ADD COLUMN IF NOT EXISTS name_ko TEXT")
    op.execute("ALTER TABLE attractions ADD COLUMN IF NOT EXISTS name_zh_cn TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE attractions DROP COLUMN IF EXISTS name_zh_cn")
    op.execute("ALTER TABLE attractions DROP COLUMN IF EXISTS name_ko")
    op.execute("ALTER TABLE attractions DROP COLUMN IF EXISTS name_ja")
