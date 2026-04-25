"""initial schema (spec M0.3)

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-25
"""
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute("""
        CREATE TABLE legal_hotels (
            id             SERIAL PRIMARY KEY,
            name           TEXT NOT NULL,
            address        TEXT NOT NULL,
            lat            FLOAT,
            lng            FLOAT,
            license_number TEXT UNIQUE,
            hotel_type     TEXT,
            source         TEXT,
            raw_data       JSONB,
            updated_at     TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX legal_hotels_name_addr_gin "
        "ON legal_hotels USING GIN (to_tsvector('simple', name || ' ' || address))"
    )

    op.execute("""
        CREATE TABLE attractions (
            id           SERIAL PRIMARY KEY,
            name         TEXT NOT NULL,
            name_en      TEXT,
            category     TEXT NOT NULL CHECK (category IN ('food', 'attraction', 'hotel')),
            lat          FLOAT NOT NULL,
            lng          FLOAT NOT NULL,
            address      TEXT,
            description  TEXT,
            tags         TEXT[],
            osm_id       BIGINT UNIQUE,
            embedding    vector(1536),
            source       TEXT DEFAULT 'osm',
            updated_at   TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX attractions_embedding_ivfflat "
        "ON attractions USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )
    op.execute("CREATE INDEX attractions_category ON attractions (category)")

    op.execute("""
        CREATE TABLE places (
            id                 SERIAL PRIMARY KEY,
            user_session_id    TEXT NOT NULL,
            name               TEXT NOT NULL,
            category           TEXT NOT NULL CHECK (category IN ('hotel', 'food', 'attraction')),
            lat                FLOAT NOT NULL,
            lng                FLOAT NOT NULL,
            address            TEXT,
            description        TEXT,
            source_type        TEXT CHECK (source_type IN ('reels_url', 'image', 'text', 'manual')),
            source_url         TEXT,
            reels_caption      TEXT,
            embedding          vector(1536),
            hotel_legal_status TEXT CHECK (hotel_legal_status IN ('legal', 'illegal', 'unknown')),
            hotel_match_id     INT REFERENCES legal_hotels(id),
            created_at         TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX places_user_session ON places (user_session_id)")
    op.execute(
        "CREATE INDEX places_embedding_ivfflat "
        "ON places USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )

    op.execute("""
        CREATE TABLE itineraries (
            id                 SERIAL PRIMARY KEY,
            user_session_id    TEXT NOT NULL,
            places_snapshot    JSONB,
            schedule           JSONB,
            weather_context    JSONB,
            generated_at       TIMESTAMPTZ DEFAULT NOW()
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS itineraries")
    op.execute("DROP TABLE IF EXISTS places")
    op.execute("DROP TABLE IF EXISTS attractions")
    op.execute("DROP TABLE IF EXISTS legal_hotels")
