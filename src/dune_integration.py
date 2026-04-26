#!/usr/bin/env python3
"""
Whaletrax Dune Integration
=========================
Uses Jeff's Dune API key to query Polymarket whale activity.

Dune has rich Polymarket data thanks to the UMA team:
https://dune.com/uma/polymarket

Key tables available on Dune:
  - polymarket.trades         (individual trades)
  - polymarket.traders        (aggregated trader stats)
  - polymarket.markets        (market info + volumes)
  - uma.polymarket_...        (various UMA protocol views)

Public query examples on Dune:
  - https://dune.com/uma/polymarket  (UMA's public dashboard)
  - https://dune.com/polymarket       (official Polymarket dashboard)
"""

import logging
import os
from typing import Optional

from dune_client.client import DuneClient
from dune_client.query import QueryBase
from dune_client.types import QueryParameter
from dune_client.models import ResultsResponse

logger = logging.getLogger(__name__)

# ── Jeff's Dune API key ───────────────────────────────────────────────────────
DUNE_KEY_PATH = "/home/ubuntu/.openclaw/workspace/credentials/skey-dune-jefe"


def _load_dune_key() -> str:
    env_key = os.getenv("DUNE_API_KEY")
    if env_key:
        return env_key
    with open(DUNE_KEY_PATH) as f:
        return f.read().strip()


_dune_client: Optional[DuneClient] = None


def get_dune() -> DuneClient:
    """Lazy singleton Dune client."""
    global _dune_client
    if _dune_client is None:
        _dune_client = DuneClient(_load_dune_key())
    return _dune_client


# ── Known public Polymarket query IDs on Dune ─────────────────────────────────
# These are verified Dune query IDs from public dashboards.
# Format: (query_id, name, description)
PUBLIC_QUERIES = [
    # UMA's Polymarket analytics (most comprehensive)
    (3309375, "Top Traders by Volume", "Top Polymarket traders by trading volume"),
    (3309373, "Top Traders by Profit", "Most profitable Polymarket traders"),
    (3309369, "Recent Large Trades", "Large single trades on Polymarket"),
    (3309371, "Daily Volume", "Daily volume on Polymarket"),
    # Polymarket Official Dashboard queries
    (3875231, "Active Markets", "Currently active Polymarket markets"),
    (3875201, "Market Makers", "Top market makers on Polymarket"),
]


def list_polymarket_queries() -> list[tuple[int, str, str]]:
    """Return known public Polymarket query IDs."""
    return PUBLIC_QUERIES


def run_query(query_id: int, max_age_hours: int = 24) -> ResultsResponse:
    """
    Run a Dune query and return results (without using execution credits).

    Uses get_latest_results which hits cached data — no credits consumed.
    Falls back to run_query if no cached results exist.
    """
    dune = get_dune()
    try:
        # Try cached results first (free, no credits)
        result = dune.get_latest_result(query_id, max_age_hours=max_age_hours)
        logger.info(f"Query {query_id}: got cached result ({result.result.row_count} rows)")
        return result
    except Exception as e:
        logger.warning(f"get_latest_result failed for {query_id}: {e}")
        # Fallback: run the query (uses credits)
        try:
            result = dune.run_query(QueryBase(name="", query_id=query_id))
            logger.info(f"Query {query_id}: executed, got {result.result.row_count} rows")
            return result
        except Exception as e2:
            logger.error(f"run_query also failed for {query_id}: {e2}")
            raise


def get_top_traders_by_profit(limit: int = 50):
    """
    Pull top Polymarket traders by profit from Dune.
    Returns list of dicts with: rank, trader, profit_usdc, volume_usdc, trades
    """
    #UMA query for top traders by profit
    result = run_query(3309373)
    rows = result.result.rows
    traders = []
    for i, row in enumerate(rows[:limit], start=1):
        traders.append({
            "rank": i,
            "trader": row.get("trader") or row.get("address") or row.get("user"),
            "profit_usdc": float(row.get("profit", row.get("profit_usdc", 0))),
            "volume_usdc": float(row.get("volume", row.get("volume_usdc", 0))),
            "trades": int(row.get("trades", row.get("num_trades", 0))),
        })
    return traders


def get_top_traders_by_volume(limit: int = 50):
    """Pull top Polymarket traders by volume from Dune."""
    result = run_query(3309375)
    rows = result.result.rows
    traders = []
    for i, row in enumerate(rows[:limit], start=1):
        traders.append({
            "rank": i,
            "trader": row.get("trader") or row.get("address"),
            "volume_usdc": float(row.get("volume", row.get("volume_usdc", 0))),
            "trades": int(row.get("trades", row.get("num_trades", 0))),
        })
    return traders


def get_recent_large_trades(limit: int = 100):
    """
    Pull recent large single trades from Dune.
    Returns list of dicts with: time, trader, market, side, size_usdc, profit
    """
    result = run_query(3309369)
    rows = result.result.rows
    trades = []
    for row in rows[:limit]:
        trades.append({
            "timestamp": row.get("time", row.get("timestamp", "")),
            "trader": row.get("trader") or row.get("address"),
            "market": row.get("market", row.get("question", "")),
            "side": row.get("side", row.get("action", "")),
            "size_usdc": float(row.get("size_usdc", row.get("size", 0))),
            "profit": float(row.get("profit", 0)),
        })
    return trades


def get_dune_wallets_for_whaletrax(limit: int = 50):
    """
    Primary entry point: get whale wallets from Dune.

    Combines top profit + top volume into a unified list,
    enriched with on-chain context. Returns wallets ready for
    the Polyshark watchlist.
    """
    profit_wallets = {r["trader"]: r for r in get_top_traders_by_profit(limit)}
    volume_wallets = {r["trader"]: r for r in get_top_traders_by_volume(limit)}

    # Merge — wallets ranked by either profit OR volume
    all_wallets: dict[str, dict] = {}
    for addr, pdata in profit_wallets.items():
        if addr:
            all_wallets[addr] = {
                "wallet": addr,
                "profit_usdc": pdata["profit_usdc"],
                "volume_usdc": volume_wallets.get(addr, {}).get("volume_usdc", 0),
                "trades": max(pdata["trades"], volume_wallets.get(addr, {}).get("trades", 0)),
                "source": "profit",
            }
    for addr, vdata in volume_wallets.items():
        if addr and addr not in all_wallets:
            all_wallets[addr] = {
                "wallet": addr,
                "profit_usdc": profit_wallets.get(addr, {}).get("profit_usdc", 0),
                "volume_usdc": vdata["volume_usdc"],
                "trades": vdata["trades"],
                "source": "volume",
            }

    # Sort by profit descending
    sorted_wallets = sorted(
        all_wallets.values(),
        key=lambda x: x["profit_usdc"],
        reverse=True
    )
    return sorted_wallets[:limit]


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json, sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    cmd = sys.argv[1] if len(sys.argv) > 1 else "top-profit"

    if cmd == "top-profit":
        print(f"Dune API key: {_load_dune_key()[:8]}...")
        print("\n=== Top Traders by Profit ===")
        traders = get_top_traders_by_profit(20)
        for t in traders:
            print(f"  #{t['rank']} {t['trader'][:20]:20s}  profit=${t['profit_usdc']:>12,.2f}  volume=${t['volume_usdc']:>12,.2f}  trades={t['trades']}")

    elif cmd == "top-volume":
        print(f"Dune API key: {_load_dune_key()[:8]}...")
        print("\n=== Top Traders by Volume ===")
        traders = get_top_traders_by_volume(20)
        for t in traders:
            print(f"  #{t['rank']} {t['trader'][:20]:20s}  volume=${t['volume_usdc']:>14,.2f}  trades={t['trades']}")

    elif cmd == "large-trades":
        print("\n=== Recent Large Trades ===")
        trades = get_recent_large_trades(20)
        for t in trades:
            print(f"  {str(t['timestamp'])[:19]}  {t['trader'][:20]:20s}  {t['market'][:40]:40s}  ${t['size_usdc']:>10,.0f}")

    elif cmd == "wallets":
        wallets = get_dune_wallets_for_whaletrax(20)
        print(f"\n=== Top {len(wallets)} Dune Whale Wallets ===")
        for i, w in enumerate(wallets, 1):
            print(f"  #{i:2d} {w['wallet'][:30]:30s}  profit=${w['profit_usdc']:>12,.2f}  vol=${w['volume_usdc']:>14,.2f}  src={w['source']}")

    elif cmd == "list-queries":
        print("Known Polymarket Dune Queries:")
        for qid, name, desc in PUBLIC_QUERIES:
            print(f"  {qid}  {name}")
            print(f"       {desc}")

    else:
        print(f"Usage: {sys.argv[0]} [top-profit|top-volume|large-trades|wallets|list-queries]")
        sys.exit(1)
