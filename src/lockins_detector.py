"""
LockIns Sniper Detector — price-bucket strategy classification for Polyshark.

Three passes:
  1. Overall — top 150 wallets by raw PnL (all prices)
  2. Penny — top 150 wallets by PnL from 90¢–99¢ entries only
  3. Nickel — top 150 wallets by PnL from 75¢–89¢ entries only

All data persisted to SQLite for backfill + delta-run efficiency.
Stores last-run timestamps so subsequent runs only fetch new records.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from . import polymarket_client as pm
from .wallet_scanner import _safe_float

logger = logging.getLogger(__name__)

# ── Paths ───────────────────────────────────────────────────────────────────────

REPO = Path(__file__).parent.parent.parent.resolve()
DB_PATH = REPO / "wallet_tracker.db"

# ── Tier constants ──────────────────────────────────────────────────────────────

TIER_OVERALL = "overall"
TIER_PENNY = "penny"
TIER_NICKEL = "nickel"
ALL_TIERS = [TIER_OVERALL, TIER_PENNY, TIER_NICKEL]

# ── Thresholds ────────────────────────────────────────────────────────────────

MIN_TRADES_OVERALL = 5
MIN_TRADES_BUCKET = 10
MIN_PROFIT_BUCKET = 50.0

DEFAULT_TOP_N = 150
DEFAULT_LIMIT = 50


# ── Dataclasses ───────────────────────────────────────────────────────────────

class PriceBucket(str, Enum):
    PENNY = "penny"
    NICKEL = "nickel"
    OTHER = "other"


@dataclass
class BucketStats:
    wallet: str
    display_name: str = ""
    bucket: PriceBucket = PriceBucket.OTHER
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    total_volume: float = 0.0
    biggest_win: float = 0.0
    biggest_loss: float = 0.0
    avg_price: float = 0.0
    win_rate_pct: float = 0.0
    avg_roi_pct: float = 0.0
    rank: int = 0
    total_profit_usdc: float = 0.0
    total_volume_usdc: float = 0.0

    @property
    def win_loss_str(self) -> str:
        return f"{self.winning_trades}/{self.losing_trades}"


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    return sqlite3.connect(str(DB_PATH))


def init_db() -> None:
    conn = _conn()
    conn.execute("CREATE TABLE IF NOT EXISTS lockins_wallets (\n        wallet TEXT PRIMARY KEY, display_name TEXT DEFAULT '')")
    conn.execute("CREATE TABLE IF NOT EXISTS lockins_stats (\n        id INTEGER PRIMARY KEY AUTOINCREMENT,\n        wallet TEXT NOT NULL, tier TEXT NOT NULL, ts INTEGER NOT NULL,\n        total_trades INTEGER DEFAULT 0, winning_trades INTEGER DEFAULT 0,\n        losing_trades INTEGER DEFAULT 0, total_pnl REAL DEFAULT 0.0,\n        total_volume REAL DEFAULT 0.0, biggest_win REAL DEFAULT 0.0,\n        biggest_loss REAL DEFAULT 0.0, avg_price REAL DEFAULT 0.0,\n        win_rate_pct REAL DEFAULT 0.0, avg_roi_pct REAL DEFAULT 0.0,\n        rank INTEGER DEFAULT 0, total_profit_usdc REAL DEFAULT 0.0,\n        total_volume_usdc REAL DEFAULT 0.0,\n        UNIQUE(wallet, tier, ts))")
    conn.execute("CREATE TABLE IF NOT EXISTS lockins_run_state (\n        tier TEXT PRIMARY KEY, last_run_ts INTEGER DEFAULT 0,\n        last_run_iso TEXT DEFAULT '')")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ls_tier ON lockins_stats(tier, ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ls_wallet ON lockins_stats(wallet)")
    conn.commit()
    conn.close()


def _ts_now() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Price bucket ────────────────────────────────────────────────────────────────

def price_bucket(price: float) -> PriceBucket:
    if price is None:
        return PriceBucket.OTHER
    if 0.90 <= price <= 0.99:
        return PriceBucket.PENNY
    if 0.70 <= price < 0.90:
        return PriceBucket.NICKEL
    return PriceBucket.OTHER


# ── Core computation ──────────────────────────────────────────────────────────

def _fetch_leaderboard(top_n: int = DEFAULT_LIMIT) -> list[dict]:
    raw = pm.get_leaderboard(limit=top_n)
    return raw if raw else []


def _fetch_closed_positions(wallet: str) -> list[dict]:
    positions = pm.get_user_closed_positions(wallet)
    return positions if isinstance(positions, list) else []


def _compute_bucket_stats(
    wallet: str,
    display_name: str,
    positions: list[dict],
    target_bucket: str,
    lb_entry: Optional[dict] = None,
    rank: int = 0,
) -> Optional[BucketStats]:
    trades_in_bucket = []
    for pos in positions:
        avg_price = _safe_float(
            pos.get("avgPrice") or pos.get("averagePrice") or pos.get("price") or 0.0
        )
        bucket = price_bucket(avg_price)

        if target_bucket == TIER_OVERALL:
            include = True
        elif target_bucket == TIER_PENNY:
            include = bucket == PriceBucket.PENNY
        elif target_bucket == TIER_NICKEL:
            include = bucket == PriceBucket.NICKEL
        else:
            include = False

        if not include:
            continue

        pnl = _safe_float(pos.get("pnl") or pos.get("profit") or pos.get("realizedPnl") or 0.0)
        cost = _safe_float(pos.get("cost") or pos.get("invested") or pos.get("costBasis") or 0.0)
        size = _safe_float(pos.get("size") or pos.get("shares") or 0.0)
        volume = cost if cost > 0 else (size * avg_price if size and avg_price else 0.0)

        trades_in_bucket.append({"pnl": pnl, "cost": cost, "volume": volume, "price": avg_price})

    total = len(trades_in_bucket)
    if total == 0:
        return None

    wins = sum(1 for t in trades_in_bucket if t["pnl"] > 0)
    losses = sum(1 for t in trades_in_bucket if t["pnl"] < 0)
    total_pnl = sum(t["pnl"] for t in trades_in_bucket)
    total_volume = sum(t["volume"] for t in trades_in_bucket)
    biggest_win = max((t["pnl"] for t in trades_in_bucket), default=0.0)
    biggest_loss = min((t["pnl"] for t in trades_in_bucket), default=0.0)
    avg_price = sum(t["price"] for t in trades_in_bucket) / total if total > 0 else 0.0
    win_rate = (wins / total * 100) if total > 0 else 0.0
    roi_sum = sum((t["pnl"] / t["cost"]) * 100 for t in trades_in_bucket if t["cost"] > 0)
    avg_roi = roi_sum / total if total > 0 else 0.0

    total_profit_lb = 0.0
    total_volume_lb = 0.0
    if lb_entry:
        total_profit_lb = _safe_float(
            lb_entry.get("profitAndLoss") or lb_entry.get("profit") or lb_entry.get("pnl") or 0.0
        )
        total_volume_lb = _safe_float(
            lb_entry.get("vol") or lb_entry.get("volume") or 0.0
        )

    return BucketStats(
        wallet=wallet,
        display_name=display_name,
        bucket=price_bucket(avg_price),
        total_trades=total,
        winning_trades=wins,
        losing_trades=losses,
        total_pnl=total_pnl,
        total_volume=total_volume,
        biggest_win=biggest_win,
        biggest_loss=biggest_loss,
        avg_price=avg_price,
        win_rate_pct=win_rate,
        avg_roi_pct=avg_roi,
        rank=rank,
        total_profit_usdc=total_profit_lb,
        total_volume_usdc=total_volume_lb,
    )


def _qualifies(stats: BucketStats, min_trades: int, min_profit: float) -> bool:
    return stats.total_trades >= min_trades and stats.total_pnl >= min_profit


# ── Per-tier scanner ───────────────────────────────────────────────────────────

def scan_tier(
    tier: str,
    top_n: int = DEFAULT_TOP_N,
    force_full: bool = False,
) -> list[BucketStats]:
    min_trades = MIN_TRADES_OVERALL if tier == TIER_OVERALL else MIN_TRADES_BUCKET
    min_profit = 0.0 if tier == TIER_OVERALL else MIN_PROFIT_BUCKET

    conn = _conn()
    init_db()

    last_ts = 0
    if not force_full:
        row = conn.execute(
            "SELECT last_run_ts FROM lockins_run_state WHERE tier=?", (tier,)
        ).fetchone()
        if row and row[0]:
            last_ts = row[0]

    is_delta = last_ts > 0 and not force_full
    logger.info(f"[{tier}] {'Delta' if is_delta else 'Full'} scan "
                f"{'(last_ts=' + str(last_ts) + ')' if is_delta else ''}")

    raw_entries = _fetch_leaderboard(top_n=DEFAULT_LIMIT)
    if not raw_entries:
        logger.warning(f"[{tier}] No leaderboard data — aborting")
        conn.close()
        return []

    lb_map: dict[str, dict] = {}
    for idx, entry in enumerate(raw_entries, start=1):
        addr = (
            entry.get("proxyWallet") or entry.get("address") or entry.get("user") or ""
        ).strip()
        if not addr.startswith("0x"):
            continue
        lb_map[addr.lower()] = {
            "name": entry.get("userName") or entry.get("displayName") or "",
            "rank": idx,
            "lb_pnl": _safe_float(entry.get("profitAndLoss") or entry.get("profit") or entry.get("pnl") or 0.0),
            "lb_vol": _safe_float(entry.get("vol") or entry.get("volume") or 0.0),
        }

    results: list[BucketStats] = []
    seen = 0
    skipped_delta = 0

    for addr, lb_data in lb_map.items():
        display_name = lb_data["name"]
        rank = lb_data["rank"]

        if is_delta:
            existing = conn.execute(
                "SELECT MAX(ts) FROM lockins_stats WHERE wallet=? AND tier=?",
                (addr, tier),
            ).fetchone()
            if existing and existing[0] and existing[0] >= last_ts:
                skipped_delta += 1
                continue

        positions = _fetch_closed_positions(addr)
        if not positions:
            continue

        stats = _compute_bucket_stats(
            wallet=addr,
            display_name=display_name,
            positions=positions,
            target_bucket=tier,
            lb_entry=lb_map.get(addr),
            rank=rank,
        )

        if stats is None:
            continue

        if tier == TIER_OVERALL:
            stats.total_profit_usdc = lb_data["lb_pnl"]
            stats.total_volume_usdc = lb_data["lb_vol"]

        if not _qualifies(stats, min_trades, min_profit):
            continue

        results.append(stats)
        seen += 1
        time.sleep(0.15)

    conn.close()

    if tier == TIER_OVERALL:
        results.sort(key=lambda r: r.total_profit_usdc, reverse=True)
    else:
        results.sort(key=lambda r: r.total_pnl, reverse=True)

    logger.info(f"[{tier}] Scanned {seen} qualifying ({skipped_delta} skipped delta), "
                f"got {len(results)} results")
    return results[:top_n]


# ── Persist ────────────────────────────────────────────────────────────────────

def persist_results(tier: str, results: list[BucketStats]) -> None:
    conn = _conn()
    init_db()
    ts = _ts_now()
    iso = _iso_now()

    for s in results:
        conn.execute(
            "INSERT OR REPLACE INTO lockins_wallets (wallet, display_name) VALUES (?, ?)",
            (s.wallet, s.display_name),
        )
        conn.execute(
            """INSERT OR REPLACE INTO lockins_stats
            (wallet, tier, ts, total_trades, winning_trades, losing_trades,
             total_pnl, total_volume, biggest_win, biggest_loss, avg_price,
             win_rate_pct, avg_roi_pct, rank, total_profit_usdc, total_volume_usdc)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (s.wallet, tier, ts, s.total_trades, s.winning_trades, s.losing_trades,
             s.total_pnl, s.total_volume, s.biggest_win, s.biggest_loss, s.avg_price,
             s.win_rate_pct, s.avg_roi_pct, s.rank, s.total_profit_usdc, s.total_volume_usdc),
        )

    conn.execute(
        "INSERT OR REPLACE INTO lockins_run_state (tier, last_run_ts, last_run_iso) VALUES (?, ?, ?)",
        (tier, ts, iso),
    )
    conn.commit()
    conn.close()
    logger.info(f"[{tier}] Persisted {len(results)} results at ts={ts}")


# ── Public API ────────────────────────────────────────────────────────────────

def run_full_scan(top_n: int = DEFAULT_TOP_N) -> dict[str, list[BucketStats]]:
    init_db()
    output = {}
    for tier in ALL_TIERS:
        results = scan_tier(tier, top_n=top_n, force_full=True)
        persist_results(tier, results)
        output[tier] = results
    return output


def run_delta_scan(top_n: int = DEFAULT_TOP_N) -> dict[str, list[BucketStats]]:
    init_db()
    output = {}
    for tier in ALL_TIERS:
        results = scan_tier(tier, top_n=top_n, force_full=False)
        persist_results(tier, results)
        output[tier] = results
    return output


def get_run_state() -> dict[str, dict]:
    init_db()
    conn = _conn()
    rows = conn.execute(
        "SELECT tier, last_run_ts, last_run_iso FROM lockins_run_state"
    ).fetchall()
    conn.close()
    return {r[0]: {"last_run_ts": r[1], "last_run_iso": r[2]} for r in rows}


def get_top_wallets(tier: str, top_n: int = DEFAULT_TOP_N) -> list[BucketStats]:
    init_db()
    conn = _conn()

    sort_col = (
        "total_profit_usdc" if tier == TIER_OVERALL else "total_pnl"
    )
    rows = conn.execute(f"""
        SELECT s.wallet, s.tier, s.ts, s.total_trades, s.winning_trades,
               s.losing_trades, s.total_pnl, s.total_volume,
               s.biggest_win, s.biggest_loss, s.avg_price,
               s.win_rate_pct, s.avg_roi_pct, s.rank,
               s.total_profit_usdc, s.total_volume_usdc,
               w.display_name
        FROM lockins_stats s
        JOIN lockins_wallets w ON w.wallet = s.wallet
        WHERE s.tier = ?
        AND s.ts = (
            SELECT MAX(ts) FROM lockins_stats
            WHERE wallet = s.wallet AND tier = s.tier
        )
        ORDER BY s.{sort_col} DESC
        LIMIT ?
    """, (tier, top_n)).fetchall()
    conn.close()

    results = []
    for r in rows:
        results.append(BucketStats(
            wallet=r[0], tier=r[1], ts=r[2],
            total_trades=r[3], winning_trades=r[4], losing_trades=r[5],
            total_pnl=r[6], total_volume=r[7], biggest_win=r[8],
            biggest_loss=r[9], avg_price=r[10], win_rate_pct=r[11],
            avg_roi_pct=r[12], rank=r[13],
            total_profit_usdc=r[14], total_volume_usdc=r[15],
            display_name=r[16] or "",
        ))
    return results
