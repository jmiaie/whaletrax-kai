"""
Compounder detector for WalletHound.

Identifies wallets that are growing their balances through compounding wins,
**not** through deposits.  Deposits and withdrawals are accounted for so that
only organic (trade-derived) growth is scored.

Strategy
--------
1. Fetch closed positions and deposit/withdrawal activity for a wallet.
2. Build a time-ordered balance history, tracking cumulative deposits and
   withdrawals alongside the running balance.
3. Compute "organic growth" = balance growth attributable to wins only.
4. Score wallets on:
   - Organic growth %  (higher = bigger compounding effect)
   - Number of profitable periods  (more = steadier growth)
   - Compounding score 0–100  (composite)
"""

from __future__ import annotations

import logging
import math

from .. import polymarket_client as pm
from ..wallet_scanner import _safe_float
from .deposit_tracker import (
    build_balance_snapshots,
    compute_totals,
    get_deposits_withdrawals,
)
from .models import GrowthMetrics

logger = logging.getLogger(__name__)

# Minimum number of closed positions to attempt growth scoring
MIN_POSITIONS_FOR_GROWTH = 3

# Number of equal-time buckets to divide the history into for period analysis
NUM_GROWTH_PERIODS = 10


def _bucket_snapshots(
    snapshots: list,
    n_buckets: int,
) -> list[list]:
    """Split snapshots into *n_buckets* roughly equal groups by index."""
    if not snapshots or n_buckets <= 0:
        return []
    size = max(1, len(snapshots) // n_buckets)
    return [snapshots[i: i + size] for i in range(0, len(snapshots), size)]


def _compounding_score(
    organic_growth_pct: float,
    winning_periods: int,
    total_periods: int,
) -> float:
    """
    Composite compounding score [0, 100].

    Components (weighted):
      50 % — organic growth %  (log-scaled, capped at 500 %)
      50 % — proportion of winning periods
    """
    growth_capped = min(abs(organic_growth_pct), 500.0)
    growth_component = (math.log1p(growth_capped) / math.log1p(500)) * 100.0
    if organic_growth_pct < 0:
        growth_component = 0.0

    period_component = (winning_periods / total_periods * 100) if total_periods > 0 else 0.0

    score = 0.50 * growth_component + 0.50 * period_component
    return round(min(score, 100.0), 1)


def analyse_wallet(wallet: str, display_name: str = "") -> GrowthMetrics:
    """
    Full compounding analysis for a single wallet.
    """
    closed_raw = pm.get_user_closed_positions(wallet)
    deposit_events = get_deposits_withdrawals(wallet)
    total_deposits, total_withdrawals = compute_totals(deposit_events)

    # Compute total profit from closed positions (this is trade-only P&L)
    total_profit = 0.0
    for pos in closed_raw:
        pnl = _safe_float(
            pos.get("pnl") or pos.get("profit") or pos.get("profitAndLoss")
            or pos.get("realizedPnl")
        )
        total_profit += pnl

    snapshots = build_balance_snapshots(wallet, closed_raw, deposit_events)

    # Determine starting and current organic balance
    starting_balance = snapshots[0].organic_balance if snapshots else 0.0
    current_balance = snapshots[-1].organic_balance if snapshots else 0.0
    organic_growth = current_balance - starting_balance

    # Organic growth % relative to starting balance or total volume
    base = abs(starting_balance) if starting_balance != 0 else 1.0
    organic_growth_pct = (organic_growth / base) * 100

    # Period analysis: bucket snapshots and count periods with positive organic delta
    buckets = _bucket_snapshots(snapshots, NUM_GROWTH_PERIODS)
    winning_periods = 0
    for bucket in buckets:
        if len(bucket) >= 2:
            delta = bucket[-1].organic_balance - bucket[0].organic_balance
            if delta > 0:
                winning_periods += 1
        elif bucket:
            # Single-element bucket; count as winning if organic_balance > 0
            if bucket[0].organic_balance > 0:
                winning_periods += 1

    total_periods = len(buckets)
    comp_score = _compounding_score(organic_growth_pct, winning_periods, total_periods)

    return GrowthMetrics(
        wallet=wallet,
        display_name=display_name,
        starting_balance_usdc=starting_balance,
        current_balance_usdc=current_balance,
        total_deposits_usdc=total_deposits,
        total_withdrawals_usdc=total_withdrawals,
        organic_growth_usdc=organic_growth,
        organic_growth_pct=round(organic_growth_pct, 2),
        total_profit_usdc=total_profit,
        num_winning_periods=winning_periods,
        num_periods=total_periods,
        compounding_score=comp_score,
        balance_snapshots=snapshots,
    )


def qualifies_as_compounder(
    metrics: GrowthMetrics,
    min_score: float = 40.0,
    min_growth_pct: float = 10.0,
) -> bool:
    """
    Return True if the wallet qualifies as a 'compounder'.
    """
    return (
        metrics.organic_growth_pct >= min_growth_pct
        and metrics.compounding_score >= min_score
        and metrics.num_winning_periods >= 2
    )
