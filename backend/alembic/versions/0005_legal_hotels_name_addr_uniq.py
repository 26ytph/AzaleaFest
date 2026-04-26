"""legal_hotels: UNIQUE (name, address)

Revision ID: 0005_hotels_name_addr_uniq
Revises: 0004_hotel_google_place_id
Create Date: 2026-04-26

Reason: 旅遊網住宿 dataset has no license_number, so the previous upsert key
(license_number UNIQUE) didn't apply to those rows — every re-run of
scripts/ingest_hotels.py would insert duplicates of the same hotel.

Adding UNIQUE (name, address) gives ingest a second upsert key that covers
the no-license-number rows, and protects regeocode_hotels_google.py from
hitting `legal_hotels_google_place_id_uniq` after duplicates accidentally
double-resolve to the same place_id.

Pre-condition (one-time): if legal_hotels currently contains duplicates,
the migration will fail. Operator should run
`TRUNCATE TABLE legal_hotels RESTART IDENTITY CASCADE` first, then
re-run fetch_hotels.py + ingest_hotels.py + regeocode_hotels_google.py.

Revision id ≤ 32 chars to fit alembic_version.version_num.
"""
from alembic import op


revision = "0005_hotels_name_addr_uniq"
down_revision = "0004_hotel_google_place_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE legal_hotels "
        "ADD CONSTRAINT legal_hotels_name_addr_uniq UNIQUE (name, address)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE legal_hotels "
        "DROP CONSTRAINT IF EXISTS legal_hotels_name_addr_uniq"
    )
