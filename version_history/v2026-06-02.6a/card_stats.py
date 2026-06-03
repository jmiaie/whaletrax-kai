"""
card_stats.py — lightweight SQLite tracker for card sends.
One row per card sent; summary queries by category / day / tier.
"""

from __future__ import annotations

import json, logging, sqlite3, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("card_stats")

DB_PATH = Path(__file__).parent / "card_stats.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    card_id        TEXT PRIMARY KEY,
    sent_at        REAL,          -- unix timestamp
    date_          TEXT,          -- YYYY-MM-DD (UTC)
    tier           TEXT,          -- 'pro' or 'free'
    channel        TEXT,          -- 'hub' / 'alerts' etc.
    market_id      TEXT,
    question       TEXT,
    category       TEXT,          -- primary category (sports/politics/weather/etc)
    subcategory    TEXT,          -- e.g. 'NBA', 'US-Election'
    wallet         TEXT,
    display_name   TEXT,
    profit_usdc    REAL,
    roi_pct        REAL,
    trade_size     REAL,
    entry_px       REAL,          -- avg_price in cents
    outcome        TEXT,          -- 'YES' / 'NO'
    end_date       TEXT,
    wr_lt          REAL,          -- lifetime win rate % at time of send
    wr_30d         REAL,          -- 30-day win rate % at time of send
    wins_lt        INTEGER,
    pos_lt         INTEGER,
    wins_30d       INTEGER,
    pos_30d        INTEGER,
    pnl_lt         REAL,
    pnl_30d        REAL,
    confidence     REAL,
    is_curated     INTEGER,       -- 1/0
    geo_available   TEXT,          -- 'US_AVAILABLE', 'NON_US_ONLY', or 'UNKNOWN'
    metadata_json  TEXT
);

CREATE TABLE IF NOT EXISTS daily_sums (
    date_          TEXT PRIMARY KEY,
    total_cards    INTEGER DEFAULT 0,
    pro_cards      INTEGER DEFAULT 0,
    free_cards     INTEGER DEFAULT 0,
    sports_cards   INTEGER DEFAULT 0,
    politics_cards INTEGER DEFAULT 0,
    other_cards    INTEGER DEFAULT 0,
    avg_roi        REAL,
    total_profit   REAL,
    updated_at     REAL
);

CREATE INDEX IF NOT EXISTS idx_cards_date   ON cards(date_);
CREATE INDEX IF NOT EXISTS idx_cards_cat   ON cards(category);
CREATE INDEX IF NOT EXISTS idx_cards_tier  ON cards(tier);
"""


def _conn() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.Connection(DB_PATH, timeout=30)
    conn.executescript(SCHEMA)
    conn.row_factory = sqlite3.Row
    return conn


def _dt() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _now() -> float:
    return time.time()


# ── public API ──────────────────────────────────────────────────────────────

def ingest_card(
    bw,
    tier: str = "pro",
    channel: str = "hub",
    card_id: Optional[str] = None,
) -> bool:
    """
    Persist a card send into the stats DB.
    bw = BigWin object (as used throughout the router).
    Returns True on success, False on failure.
    """
    try:
        c = _conn()
        now_ts = _now()
        today  = _dt()

        # Derive category from bw.cats or question text
        cats = getattr(bw, "cats", None)
        if cats:
            if isinstance(cats, list) and cats:
                primary_cat = cats[0].lower().strip()
            elif isinstance(cats, str):
                try:
                    cats_list = json.loads(cats)
                    primary_cat = cats_list[0].lower().strip() if cats_list else "other"
                except Exception:
                    primary_cat = cats.lower().strip() or "other"
            else:
                primary_cat = "other"
        else:
            primary_cat = _categorise_question(getattr(bw, "market_question", "") or "")

        card_id_str = card_id or f"{getattr(bw, 'market_id', '?')}_{int(now_ts)}"

        row = {
            "card_id":       card_id_str,
            "sent_at":       now_ts,
            "date_":         today,
            "tier":          tier,
            "channel":       channel,
            "market_id":     getattr(bw, "market_id", "") or "",
            "question":      (getattr(bw, "market_question", "") or "")[:500],
            "category":      primary_cat,
            "subcategory":   _subcategory(primary_cat, getattr(bw, "market_question", "") or ""),
            "wallet":        getattr(bw, "wallet", "") or "",
            "display_name":  getattr(bw, "display_name", "") or "",
            "profit_usdc":   float(getattr(bw, "profit_usdc", 0) or 0),
            "roi_pct":       float(getattr(bw, "roi_pct", 0) or 0),
            "trade_size":    float(getattr(bw, "trade_size_usdc", 0) or 0),
            "entry_px":      float(getattr(bw, "avg_price", 0) or 0) * 100,  # cents
            "outcome":       getattr(bw, "outcome", "") or "",
            "end_date":      getattr(bw, "end_date", "") or "",
            "wr_lt":         float(getattr(bw, "win_rate", 0) or 0),
            "wr_30d":        float(getattr(bw, "win_rate_30d", 0) or 0),
            "wins_lt":       int(getattr(bw, "wins_lt", 0) or 0),
            "pos_lt":        int(getattr(bw, "pos_lt", 0) or 0),
            "wins_30d":      int(getattr(bw, "wins_30d", 0) or 0),
            "pos_30d":       int(getattr(bw, "pos_30d", 0) or 0),
            "pnl_lt":        float(getattr(bw, "total_pnl", 0) or 0),
            "pnl_30d":       float(getattr(bw, "pnl_30d", 0) or 0),
            "confidence":    float(getattr(bw, "confidence", 0) or 0),
            "is_curated":    1 if getattr(bw, "is_curated", False) else 0,
            "geo_available": getattr(bw, "geo_available", "UNKNOWN") or "UNKNOWN",
            "metadata_json": json.dumps({
                "win_streak": getattr(bw, "win_streak", 0),
                "source":     "polyshark_router",
            }),
        }

        cols = ", ".join(row.keys())
        vals = ", ".join([f":{k}" for k in row])
        c.execute(f"INSERT OR IGNORE INTO cards ({cols}) VALUES ({vals})", row)

        # Upsert daily sums
        cat_col = f"{primary_cat}_cards" if primary_cat in (
            "sports", "politics", "weather", "entertainment",
            "economics", "crypto", "other"
        ) else None

        cur = c.execute(
            "SELECT total_cards FROM daily_sums WHERE date_ = :today",
            {"today": today},
        )
        existing = cur.fetchone()

        if existing:
            upd = ["total_cards = total_cards + 1"]
            if tier == "pro":
                upd.append("pro_cards = pro_cards + 1")
            else:
                upd.append("free_cards = free_cards + 1")
            if cat_col:
                upd.append(f"{cat_col} = {cat_col} + 1")
            upd.append("updated_at = :now_ts")
            c.execute(
                f"UPDATE daily_sums SET {', '.join(upd)} WHERE date_ = :today",
                {"today": today, "now_ts": now_ts},
            )
        else:
            c.execute(
                """INSERT INTO daily_sums
                   (date_, total_cards, pro_cards, free_cards,
                    sports_cards, politics_cards, other_cards, updated_at)
                   VALUES (:today, 1,
                           :is_pro, :is_free, :sports, :politics, :other, :now_ts)""",
                {
                    "today":   today,
                    "is_pro":  1 if tier == "pro" else 0,
                    "is_free": 1 if tier == "free" else 0,
                    "sports":  1 if primary_cat == "sports" else 0,
                    "politics":1 if primary_cat == "politics" else 0,
                    "other":   1 if primary_cat not in ("sports", "politics") else 0,
                    "now_ts":  now_ts,
                },
            )

        c.commit()
        c.close()
        log.debug(f"card_stats: ingested {card_id_str} [{primary_cat}]")
        return True

    except Exception as e:
        log.warning(f"card_stats: ingest failed — {e}")
        return False


def get_daily_counts(date: Optional[str] = None) -> dict:
    """Return card counts by category for a given date (YYYY-MM-DD). Default: today."""
    d = date or _dt()
    try:
        c = _conn()
        cur = c.execute("SELECT * FROM daily_sums WHERE date_ = :d", {"d": d})
        row = cur.fetchone()
        c.close()
        if row:
            return dict(row)
    except Exception as e:
        log.warning(f"card_stats: query failed — {e}")
    return {}


def get_category_breakdown(days: int = 7) -> list[dict]:
    """Return card counts per category over the last N days."""
    try:
        c = _conn()
        rows = c.execute(
            """SELECT category, COUNT(*) as cnt
               FROM cards
               WHERE sent_at >= :since
               GROUP BY category
               ORDER BY cnt DESC""",
            {"since": time.time() - days * 86400},
        ).fetchall()
        c.close()
        return [dict(r) for r in rows]
    except Exception as e:
        log.warning(f"card_stats: breakdown query failed — {e}")
        return []


# ── helpers ──────────────────────────────────────────────────────────────────

def _categorise_question(q: str) -> str:
    q_lower = q.lower()
    keywords = {
        "sports": [
            "vs", " vs ", " vs.", "game", "match", "league", "season",
            "win", "lose", "championship", "playoffs", "final",
            "nba", "nfl", "mlb", "nhl", "mma", "ufc", "boxing",
            "tennis", "golf", "soccer", "football", "baseball",
            "basketball", "storm", "marlins", "royals", "tigers", "rays",
            "giants", "brewers", "white sox", "twins", "rangers", "cardinals",
        ],
        "politics": [
            "election", "president", "congress", "senate", "house",
            "governor", "mayor", "vote", "ballot", "polling",
            "trump", "biden", "obama", "republican", "democrat",
            "gop", "primary", "runoff",
        ],
        "weather": [
            "hurricane", "typhoon", "storm", "flood", "earthquake",
            "tornado", "blizzard", "rain", "snow", "temperature",
            "forecast", "precipitation",
        ],
        "economics": [
            "fed", "inflation", "gdp", "unemployment", "interest rate",
            "recession", "economy", "jobs", "market",
        ],
        "crypto": [
            "bitcoin", "ethereum", "eth ", "btc", "crypto", "defi",
            "solana", "token", "blockchain",
        ],
        "entertainment": [
            "award", "oscar", "grammy", "emmy", "golden globe",
            "movie", "album", "song", "film", "series", "netflix",
        ],
    }
    for cat, kws in keywords.items():
        if any(kw in q_lower for kw in kws):
            return cat
    return "other"


def _subcategory(cat: str, q: str) -> str:
    q_lower = q.lower()
    if cat == "sports":
        for sport in ["nba", "nfl", "mlb", "nhl", "ufc", "mma", "boxing",
                      "tennis", "golf", "soccer", "tennis"]:
            if sport in q_lower:
                return sport.upper()
        if " vs " in q_lower or " vs." in q_lower:
            return "MATCHUP"
        return "OTHER"
    if cat == "politics":
        if "senate" in q_lower or "congress" in q_lower:
            return "US-LEGISLATIVE"
        if "governor" in q_lower:
            return "GOV-RACE"
        if any(w in q_lower for w in ["trump", "biden", "obama"]):
            return "US-ELECTION"
        return "OTHER"
    return "OTHER"