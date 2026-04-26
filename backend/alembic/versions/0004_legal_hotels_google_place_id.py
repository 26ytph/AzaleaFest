"""legal_hotels.google_place_id

Revision ID: 0004_hotel_google_place_id
Revises: 0003_name_translations
Create Date: 2026-04-26

Adds the google_place_id column used by the M4 matcher's place_id exact-match
path. Backfilled by scripts/regeocode_hotels_google.py via the Google Places
API v1 :searchText endpoint.

Revision id deliberately kept ≤ 32 chars so it fits the default
alembic_version.version_num varchar(32).
"""
from alembic import op


revision = "0004_hotel_google_place_id"
down_revision = "0003_name_translations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE legal_hotels ADD COLUMN IF NOT EXISTS google_place_id TEXT"
    )
    # Partial unique: only enforce on non-null values, so rows that Google
    # cannot resolve still coexist.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS legal_hotels_google_place_id_uniq "
        "ON legal_hotels (google_place_id) WHERE google_place_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS legal_hotels_google_place_id_uniq")
    op.execute("ALTER TABLE legal_hotels DROP COLUMN IF EXISTS google_place_id")
