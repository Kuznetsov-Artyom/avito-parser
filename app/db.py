"""SQLite-хранилище: история поисков + результаты.

Используется стандартная sqlite3 (потокобезопасность через check_same_thread=False
и один lock — нагрузка личного уровня, этого достаточно).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone

from .config import DATA_DIR, DB_PATH

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS searches (
    id         TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    query      TEXT NOT NULL,
    city       TEXT NOT NULL,
    status     TEXT NOT NULL,           -- pending | running | done | error
    total      INTEGER NOT NULL DEFAULT 0,
    processed  INTEGER NOT NULL DEFAULT 0,
    current_step TEXT,
    error      TEXT,
    params     TEXT NOT NULL            -- JSON исходного запроса
);

CREATE TABLE IF NOT EXISTS listings (
    search_id TEXT NOT NULL REFERENCES searches(id),
    avito_id  TEXT NOT NULL,
    title     TEXT,
    price     INTEGER,
    url       TEXT,
    image_url TEXT,
    location_text TEXT,
    lat REAL, lng REAL,
    distance_km REAL,
    description TEXT,
    seller_name TEXT, seller_rating REAL, seller_reviews INTEGER,
    seller_since INTEGER, seller_badges TEXT,   -- JSON-список
    rel_score REAL, price_score REAL, dist_score REAL, total_score REAL,
    PRIMARY KEY (search_id, avito_id)
);
"""


def init_db() -> None:
    global _conn
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    with _lock, _conn:
        _conn.executescript(_SCHEMA)


def _get_conn() -> sqlite3.Connection:
    if _conn is None:
        init_db()
    assert _conn is not None
    return _conn


def create_search(query: str, city: str, params: dict) -> str:
    search_id = uuid.uuid4().hex[:12]
    with _lock, _get_conn() as c:
        c.execute(
            "INSERT INTO searches (id, created_at, query, city, status, params) VALUES (?,?,?,?,?,?)",
            (search_id, datetime.now(timezone.utc).isoformat(), query, city, "pending",
             json.dumps(params, ensure_ascii=False)),
        )
    return search_id


def update_search(search_id: str, **fields) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    with _lock, _get_conn() as c:
        c.execute(f"UPDATE searches SET {cols} WHERE id=?", (*fields.values(), search_id))


def get_search(search_id: str) -> dict | None:
    with _lock:
        row = _get_conn().execute("SELECT * FROM searches WHERE id=?", (search_id,)).fetchone()
    return dict(row) if row else None


def save_listing(search_id: str, listing_dict: dict) -> None:
    d = listing_dict
    with _lock, _get_conn() as c:
        c.execute(
            """INSERT OR REPLACE INTO listings
               (search_id, avito_id, title, price, url, image_url, location_text,
                lat, lng, distance_km, description,
                seller_name, seller_rating, seller_reviews, seller_since, seller_badges,
                rel_score, price_score, dist_score, total_score)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (search_id, d["avito_id"], d.get("title"), d.get("price"), d.get("url"),
             d.get("image_url"), d.get("location_text"),
             d.get("lat"), d.get("lng"), d.get("distance_km"), d.get("description"),
             d.get("seller_name"), d.get("seller_rating"), d.get("seller_reviews"),
             d.get("seller_since"),
             json.dumps(d.get("seller_badges") or [], ensure_ascii=False),
             d.get("rel_score"), d.get("price_score"), d.get("dist_score"), d.get("total_score")),
        )


def get_listings(search_id: str) -> list[dict]:
    with _lock:
        rows = _get_conn()
        rows = _get_conn().execute(
            "SELECT * FROM listings WHERE search_id=? ORDER BY total_score DESC", (search_id,)
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["seller_badges"] = json.loads(d.get("seller_badges") or "[]")
        out.append(d)
    return out


def listing_exists(search_id: str, avito_id: str) -> bool:
    with _lock:
        row = _get_conn().execute(
            "SELECT 1 FROM listings WHERE search_id=? AND avito_id=?", (search_id, avito_id)
        ).fetchone()
    return row is not None


def search_history(prefix: str, limit: int = 5) -> list[str]:
    """Уникальные прошлые запросы, начинающиеся с prefix — для автодополнения."""
    with _lock:
        rows = _get_conn().execute(
            "SELECT DISTINCT query FROM searches "
            "WHERE query LIKE ? AND LOWER(query) != LOWER(?) "
            "ORDER BY created_at DESC LIMIT ?",
            (f"{prefix}%", prefix.strip(), limit),
        ).fetchall()
    return [r["query"] for r in rows]
