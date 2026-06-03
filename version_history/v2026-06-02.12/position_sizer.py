#!/usr/bin/env python3
"""
POSITION SIZER — v1.0
Tiered position sizing for Polymarket.
Scales with account balance, respects market liquidity.
Each position capped independently. Multiple positions per day supported.
"""
from datetime import datetime, timezone
from pathlib import Path

# ── Tiered caps (per position, not total) ─────────────────────────────────────
# These reflect real Polymarket market depth:
# - Small markets ($100K-500K vol): cap $200-500
# - Medium markets ($1-5M vol): cap $500-2,500
# - Large markets ($10-50M vol): cap $2,500-10,000

POSITION_CAPS = [
    (5_000,      500),     # $0-$5K balance: $500 per position
    (20_000,    1_000),    # $5K-$20K: $1,000 per position
    (50_000,    2_500),    # $20K-$50K: $2,500 per position
    (200_000,   5_000),    # $50K-$200K: $5,000 per position
    (float('inf'), 10_000), # $200K+: $10,000 per position
]

def get_cap(balance: float) -> float:
    """Return the per-position cap for a given balance."""
    for threshold, cap in POSITION_CAPS:
        if balance <= threshold:
            return cap
    return 10_000

def calc_position_size(balance: float, fraction: float, n_positions: int = 1) -> list[float]:
    """
    Calculate position size(s) for a given balance and fraction.
    Returns list of position sizes (one per trade).
    
    Args:
        balance: current account balance
        fraction: total daily exposure fraction (e.g. 0.25 = 25%)
        n_positions: number of positions to split across (default 1)
    
    Returns:
        list of position sizes (floats), each capped at tiered limit
    """
    if n_positions < 1:
        n_positions = 1
    
    per_trade_frac = fraction / n_positions
    cap = get_cap(balance)
    
    positions = []
    for _ in range(n_positions):
        raw = balance * per_trade_frac
        size = max(min(raw, cap), 2.00)
        positions.append(round(size, 2))
    
    return positions

def total_deployed(positions: list[float]) -> float:
    """Sum of all positions in a set."""
    return sum(positions)

def effective_fraction(balance: float, positions: list[float]) -> float:
    """What fraction of balance is actually deployed?"""
    if balance <= 0:
        return 0.0
    return sum(positions) / balance

def tier_info(balance: float) -> dict:
    """Return the tier info for a given balance."""
    cap = get_cap(balance)
    for threshold, cap_val in reversed(POSITION_CAPS):
        if balance > threshold:
            prev_threshold = threshold
            prev_cap = cap_val
            break
    else:
        prev_threshold = 0
        prev_cap = 500
    
    # Next tier
    next_threshold = None
    next_cap = None
    for threshold, cap_val in POSITION_CAPS:
        if threshold >= balance and threshold > 0:
            next_threshold = threshold
            next_cap = cap_val
            break
    
    return {
        'current_cap': cap,
        'balance': balance,
        'next_tier_threshold': next_threshold,
        'next_tier_cap': next_cap,
    }

# ── Tiered sizing table ──────────────────────────────────────────────────────
def print_tier_map():
    print("TIERED POSITION SIZER — SCALE WITH BALANCE")
    print(f"{'Balance':>12}  {'Cap/Pos':>8}  {'Next Tier':>12}  {'Eff Frac@25%':>14}  {'Eff Frac@30%':>14}")
    print("-" * 65)
    for balance in [500, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000, 500000]:
        cap = get_cap(balance)
        # Find next tier
        next_t = next((f"${t:,}" for t, c in POSITION_CAPS if t > balance), "max")
        eff_25 = min(balance * 0.25, cap) / balance * 100
        eff_30 = min(balance * 0.30, cap) / balance * 100
        print(f"  ${balance:>10,.0f}  ${cap:>6,.0f}  {next_t:>12}  {eff_25:>12.1f}%  {eff_30:>12.1f}%")

if __name__ == '__main__':
    print_tier_map()