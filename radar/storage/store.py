"""Deduplicación persistente en SQLite (data/radar.db).

Se persiste entre ejecuciones porque GitHub Actions lo commitea de vuelta al
repositorio al final de cada ciclo (ver .github/workflows/radar.yml).
Estados: published (nunca se repite), rejected (TTL), rule_dropped (TTL).

Además de la tabla `seen`, guarda un SNAPSHOT completo de cada oferta
publicado (tabla `deals`): es la materia prima del sitio estático de
captación (radar/publish/web.py), que se regenera desde aquí en cada ciclo.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen (
    deal_id    TEXT PRIMARY KEY,
    url        TEXT,
    title      TEXT,
    status     TEXT NOT NULL,
    score      REAL,
    first_seen TEXT NOT NULL,
    last_seen  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_seen_status ON seen(status);

CREATE TABLE IF NOT EXISTS deals (
    deal_id      TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    url          TEXT,
    asin         TEXT,
    brand        TEXT,
    price        REAL,
    list_price   REAL,
    discount     REAL,
    rating       REAL,
    reviews      INTEGER,
    image_url    TEXT,
    score        REAL,
    verdict_msg  TEXT,
    aff_url      TEXT,
    published_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_deals_pub ON deals(published_at);
"""


class SeenStore:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    # ------------------------------------------------------------ consultas --
    def is_new(self, deal_id: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM seen WHERE deal_id = ?", (deal_id,)).fetchone()
        return row is None

    def stats(self) -> dict[str, int]:
        return {
            status: count
            for status, count in self.conn.execute(
                "SELECT status, COUNT(*) FROM seen GROUP BY status"
            )
        }

    # ------------------------------------------------------------- escritura --
    def mark(self, deal, status: str, score: float | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.conn.execute(
            """
            INSERT INTO seen (deal_id, url, title, status, score, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(deal_id) DO UPDATE SET
                status = excluded.status,
                score = excluded.score,
                last_seen = excluded.last_seen
            """,
            (deal.id, deal.url, deal.title[:300], status, score, now, now),
        )
        self.conn.commit()

    # ------------------------------------------------- snapshot de publicados --
    def save_published(self, deal, score: float | None = None,
                       verdict_message: str | None = None,
                       aff_url: str | None = None) -> None:
        """Guarda/reemplaza el snapshot completo de una oferta publicada."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.conn.execute(
            """
            INSERT INTO deals (deal_id, title, url, asin, brand, price, list_price,
                               discount, rating, reviews, image_url, score,
                               verdict_msg, aff_url, published_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(deal_id) DO UPDATE SET
                title = excluded.title,
                price = excluded.price,
                list_price = excluded.list_price,
                discount = excluded.discount,
                rating = excluded.rating,
                reviews = excluded.reviews,
                image_url = excluded.image_url,
                score = excluded.score,
                verdict_msg = excluded.verdict_msg,
                aff_url = excluded.aff_url,
                published_at = excluded.published_at
            """,
            (
                deal.id, deal.title[:300], deal.url, deal.asin, deal.brand,
                deal.current_price, deal.list_price, deal.discount_pct,
                deal.rating, deal.reviews, deal.image_url, score,
                verdict_message, aff_url, now,
            ),
        )
        self.conn.commit()

    def published_deals(self, limit: int = 60) -> list[dict]:
        """Snapshots de ofertas publicadas, del más nuevo al más viejo."""
        cur = self.conn.execute(
            """
            SELECT deal_id, title, url, asin, brand, price, list_price, discount,
                   rating, reviews, image_url, score, verdict_msg, aff_url, published_at
            FROM deals ORDER BY published_at DESC LIMIT ?
            """,
            (int(limit),),
        )
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def published_count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) FROM deals").fetchone()
        return int(row[0]) if row else 0

    def purge(self, rejected_ttl_days: int) -> int:
        """Borra rechazos antiguos para poder re-evaluar ofertas en el futuro."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=rejected_ttl_days)).isoformat(
            timespec="seconds"
        )
        cur = self.conn.execute(
            "DELETE FROM seen WHERE status != 'published' AND last_seen < ?", (cutoff,)
        )
        self.conn.commit()
        return cur.rowcount or 0

    def close(self) -> None:
        self.conn.close()
