"""
Big-win detector: surfaces single-trade events that qualify as "big wins".

ARCHITECTURE (June 2026 refactor):
  PRIMARY — scan OPEN positions via get_user_positions()
 Detects whale entries while markets are still live.
             CLOB price at detection time becomes current_price on the BigWin.
             Cards fire immediately with live entry vs current price context.

  STATS ONLY — scan CLOSED positions via get_user_closed_positions()
             Used ONLY to update wallet profiles (win rate, P&L, streak).
             No cards emitted from closed positions.
             Profiles feed the win-rate / P&L stats on open-position cards.

A "big win" open position:
  • trade_size_usdc >= BIG_WIN_MIN_TRADE_SIZE_USDC  (cost basis)
  • Entry price < 95¢  (leaves room for the market to move — NOT a near-resolved punt)
  • Market is accepting orders (not resolved)

  ROI and profit_usdc for open positions reflect the ENTRY position,
  not a realized close. Cards show "potential ROI" in open state.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from . import config, polymarket_client as pm
from .models import BigWin, WalletStats
from .wallet_scanner import _safe_float
from .parsers import parse_leaderboard_entry

logger = logging.getLogger(__name__)


# ── Open-position detection (PRIMARY) ─────────────────────────────────────────

def _open_position_to_big_win(
    raw: dict[str, Any],
    wallet: str,
    display_name: str,
    current_price: float = 0.0,
) -> Optional[BigWin]:
    """
    Convert a single open-position dict into a BigWin (is_open=True).
    Returns None if the position doesn't qualify as a big-win entry,
    or if the market has already resolved (no alert value in a resolved market).

    Filters:
      - redeemable=True → market resolved, skip entirely
      - percentPnl <= -99 → market effectively resolved (position near-zero value)
      - Must have a cost basis (size * avg_price in USDC)
      - Entry price must be < 95¢  (avoids near-resolved noise)
    """
    # Skip resolved markets — no alert value in a closed market
    if raw.get('redeemable') is True:
        return None
    # Additional resolution check: near-zero current value means market resolved
    pct_pnl = float(raw.get('percentPnl', 0) or 0)
    if pct_pnl <= -99:
        return None
    # Time-based resolution check: if endDate is in the past, market has resolved
    end_date_str = str(raw.get('endDate', '') or '')
    if end_date_str:
        try:
            from datetime import datetime, timezone
            end_dt_str = end_date_str.replace('Z', '+00:00')
            end_dt = datetime.fromisoformat(end_dt_str)
            # Ensure both are timezone-aware for comparison
            now_utc = datetime.now(timezone.utc)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
            if end_dt < now_utc:
                return None
        except Exception:
            pass

    size      = _safe_float(raw.get("size") or raw.get("shares") or raw.get("totalBought") or 0)
    avg_price = _safe_float(raw.get("avgPrice") or raw.get("price") or 0)
    cost      = _safe_float(raw.get("cost") or raw.get("invested") or raw.get("costBasis") or 0)
    if not cost and size > 0 and avg_price > 0:
        cost = size * avg_price

    if not cost or cost < config.BIG_WIN_MIN_TRADE_SIZE_USDC:
        return None

    # Reject near-resolved entries — whale entered too late
    if avg_price >= 0.95:
        return None

    question  = str(raw.get("question") or raw.get("title") or raw.get("marketTitle") or "Unknown")
    market_id = str(raw.get("conditionId") or raw.get("market") or raw.get("marketId") or "")
    trade_id  = str(raw.get("id") or raw.get("tradeId") or raw.get("positionId") or "")
    # Use createdAt as proxy for position open time (no direct 'openedAt' field)
    timestamp = int(_safe_float(raw.get("createdAt") or raw.get("timestamp") or 0))
    if not timestamp:
        timestamp = int(_safe_float(raw.get("eventStartDate") or 0))

    # Current price: prefer curPrice from position data (authoritative — it's the
    # whale's own outcome's current price). CLOB 'tokens' approach fails for
    # team-name markets where outcomes are team names, not "Yes"/"No".
    # CLOB fallback is only used when curPrice is 0/unavailable.
    cur_price_raw = _safe_float(raw.get('curPrice') or 0)
    if cur_price_raw > 0:
        current_price = cur_price_raw
    # else use the CLOB-fetched current_price parameter (may be 0 for team markets)

    # roi_pct based on current_price vs entry (unrealized gain so far)
    roi_pct = 0.0
    if current_price > 0 and avg_price > 0:
        roi_pct = ((current_price - avg_price) / avg_price) * 100

    # unrealized P&L = (current_price - avg_price) * size
    unrealized_pnl = (current_price - avg_price) * size if current_price > 0 else cash_pnl

    # outcome: derive YES/NO from avgPrice
    raw_outcome = raw.get("outcome") or ""
    if raw_outcome in ("", None):
        if avg_price > 0.55:
            raw_outcome = "YES"
        elif avg_price > 0 and avg_price < 0.45:
            raw_outcome = "NO"
        else:
            raw_outcome = str(raw.get("outcomeIndex", "N/A"))
    outcome = str(raw_outcome)

    # Market slug from position data (already provided by Polymarket)
    market_slug = str(raw.get('slug', '') or '')

    return BigWin(
        wallet=wallet,
        display_name=display_name,
        market_question=question,
        outcome=outcome,
        profit_usdc=cost,           # cost basis as "profit_usdc" for open positions
        roi_pct=roi_pct,            # unrealized ROI vs current CLOB price
        trade_size_usdc=cost,
        timestamp=timestamp,
        market_id=market_id,
        trade_id=trade_id,
        end_date=str(raw.get('endDate', '')),
        avg_price=avg_price,
        is_open=True,
        current_price=current_price,
        unrealized_pnl=unrealized_pnl,
        market_slug=market_slug,
    )


def _leaderboard_wallet_to_open_positions(entry_raw: dict[str, Any], rank: int) -> list[BigWin]:
    """
    For a single leaderboard entry: fetch their OPEN positions and
    surface any that qualify as big-win entries (is_open=True).
    """
    entry = parse_leaderboard_entry(entry_raw, rank)
    if not entry.proxy_wallet:
        return []

    big_wins: list[BigWin] = []
    open_pos = pm.get_user_positions(entry.proxy_wallet)
    # Filter to only active (non-resolved) positions for both big-win detection
    # AND profile updates. Resolved positions (redeemable=True, percentPnl=-100)
    # would be counted as losses in the profile, skewing win rate.
    active_pos = [
        p for p in open_pos
        if not p.get('redeemable') is True
        and float(p.get('percentPnl', 0) or 0) > -99
    ]
    for pos in active_pos:
        market_id = str(pos.get("conditionId") or pos.get("market") or pos.get("marketId") or "")
        # Fetch current CLOB price for this market
        current_price = _fetch_current_price(market_id)
        bw = _open_position_to_big_win(pos, entry.proxy_wallet, entry.name, current_price)
        if bw:
            bw.leaderboard_volume = entry.volume_usdc
            big_wins.append(bw)

    # Update wallet profile with active positions for stats (not resolved ones)
    from wallet_profiles import get_profile, update_profile
    profile = get_profile(entry.proxy_wallet)
    profile.name = entry.name
    if active_pos:
        update_profile(entry.proxy_wallet, entry.name, active_pos)
    profile = get_profile(entry.proxy_wallet)
    profile.name = entry.name
    inverse, reason = _classify_inverse_candidate(profile)
    for bw in big_wins:
        bw.win_rate = profile.win_rate
        bw.win_rate_30d = profile.win_rate_30d
        bw.win_streak = profile.current_streak
        bw.inverse_candidate = inverse
        bw.inverse_reason = reason

    return big_wins


def _fetch_current_price(market_id: str) -> float:
    """Fetch the current YES price from Polymarket CLOB API for a market.
    
    Polymarket CLOB market endpoint returns prices in the 'tokens' array:
      tokens[i] = {outcome: "Yes", price: 0.45, ...}
    The YES outcome token's price is the current market price.
    """
    try:
        import urllib.request
        url = f"https://clob.polymarket.com/markets/{market_id}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        # Primary: tokens array — each token has outcome + price
        tokens = data.get("tokens", [])
        for token in tokens:
            outcome = str(token.get("outcome", "")).lower()
            if outcome == "yes":
                price = token.get("price")
                if price is not None:
                    return float(price)
        # Fallback: outcomePrices dict (legacy format)
        outcome_prices = data.get("outcomePrices", {})
        if isinstance(outcome_prices, dict):
            for key in ("YES", "yes", "Yes"):
                if key in outcome_prices:
                    val = outcome_prices[key]
                    if val:
                        return float(val)
    except Exception:
        pass
    return 0.0


def scan_open_positions_from_leaderboard(top_n: int = config.LEADERBOARD_TOP_N) -> list[BigWin]:
    """
    PRIMARY DETECTION PATH.
    Pull the top-N leaderboard wallets and find all qualifying big-win OPEN positions.
    Returns BigWin objects with is_open=True, sorted by trade_size_usdc descending.
    """
    raw_entries = pm.get_leaderboard(limit=top_n)
    if not raw_entries:
        logger.warning("Leaderboard returned no data — cannot scan open positions.")
        return []

    all_bw: list[BigWin] = []
    for idx, raw in enumerate(raw_entries[:top_n], start=1):
        bws = _leaderboard_wallet_to_open_positions(raw, idx)
        all_bw.extend(bws)

    all_bw.sort(key=lambda bw: bw.trade_size_usdc, reverse=True)
    return all_bw


# ── Closed-position detection (STATS ONLY) ─────────────────────────────────────

def _closed_position_to_big_win(raw: dict[str, Any], wallet: str, display_name: str) -> Optional[BigWin]:
    """
    Try to extract a BigWin from a single raw closed-position dict.
    Returns None if the position doesn't qualify.

    NOTE: This path is STATS ONLY. BigWins from closed positions are used only to
    update wallet profiles. No cards are emitted from these events.
    """
    pnl = _safe_float(
        raw.get("pnl") or raw.get("profit") or raw.get("profitAndLoss") or raw.get("realizedPnl")
    )
    cost = _safe_float(raw.get("cost") or raw.get("invested") or raw.get("costBasis"))
    if not cost:
        total_bought = _safe_float(raw.get("totalBought") or raw.get("amount") or 0)
        avg_price = _safe_float(raw.get("avgPrice") or raw.get("price") or 0)
        if total_bought and avg_price:
            cost = total_bought * avg_price
        elif total_bought:
            cost = total_bought
    raw_outcome = raw.get("outcome") or ""
    if raw_outcome in ("", None):
        ap = _safe_float(raw.get("avgPrice") or 0)
        if ap > 0.55:
            raw_outcome = "YES"
        elif ap > 0 and ap < 0.45:
            raw_outcome = "NO"
        else:
            raw_outcome = str(raw.get("outcomeIndex", "N/A"))
    outcome = str(raw_outcome)
    question = str(raw.get("question") or raw.get("title") or raw.get("marketTitle") or "Unknown")
    market_id = str(raw.get("market") or raw.get("marketId") or raw.get("conditionId") or "")
    trade_id = str(raw.get("id") or raw.get("tradeId") or "")
    timestamp = int(_safe_float(raw.get("timestamp") or raw.get("createdAt") or raw.get("time")))
    roi = (pnl / cost * 100) if cost > 0 else 0.0
    if (
        pnl >= config.BIG_WIN_MIN_PROFIT_USDC
        and roi >= config.BIG_WIN_MIN_ROI_PCT
        and cost >= config.BIG_WIN_MIN_TRADE_SIZE_USDC
    ):
        end_date = str(raw.get("endDate") or "")
        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                if end_dt < datetime(2025, 2, 1, tzinfo=timezone.utc):
                    return None
            except Exception:
                pass
        avg_price = _safe_float(raw.get("avgPrice") or 0)
        return BigWin(
            wallet=wallet,
            display_name=display_name,
            market_question=question,
            outcome=outcome,
            profit_usdc=pnl,
            roi_pct=roi,
            trade_size_usdc=cost,
            timestamp=timestamp,
            market_id=market_id,
            trade_id=trade_id,
            end_date=end_date,
            avg_price=avg_price,
            is_open=False,
        )
    return None


def _leaderboard_wallet_to_big_wins(entry_raw: dict[str, Any], rank: int) -> list[BigWin]:
    """
    STATS-ONLY PATH: fetch closed positions and update wallet profile.
    Returns empty list — closed-position BigWins are NOT emitted as alerts.
    """
    entry = parse_leaderboard_entry(entry_raw, rank)
    if not entry.proxy_wallet:
        return []

    closed = pm.get_user_closed_positions(entry.proxy_wallet)
    if not closed:
        return []

    # Update profile only — no card emission
    from wallet_profiles import get_profile, update_profile
    profile = get_profile(entry.proxy_wallet)
    profile.name = entry.name
    update_profile(entry.proxy_wallet, entry.name, closed)
    return []


def _classify_inverse_candidate(profile) -> tuple[bool, str]:
    """Flag wallets that are better treated as inverse/fade candidates."""
    try:
        total = int(getattr(profile, 'total_positions', 0) or 0)
        wr = float(getattr(profile, 'win_rate', 0) or 0)
        wr30 = float(getattr(profile, 'win_rate_30d', 0) or 0)
        pnl = float(getattr(profile, 'total_pnl', 0) or 0)
        pnl30 = float(getattr(profile, 'pnl_30d', 0) or 0)
    except Exception:
        return False, ''
    if total >= 10 and wr <= 10 and wr30 <= 10:
        return True, f'Persistent loser: {wr:.1f}% lifetime WR / {wr30:.1f}% 30D WR'
    if total >= 20 and pnl < 0 and pnl30 <= 0:
        return True, f'Negative P/L: {pnl:,.0f} lifetime / {pnl30:,.0f} 30D'
    return False, ''


# ── Public API ──────────────────────────────────────────────────────────────────

def scan_big_wins_from_leaderboard(top_n: int = config.LEADERBOARD_TOP_N) -> list[BigWin]:
    """
    STATS-ONLY entry point (backward compatibility).
    Updates wallet profiles from closed positions but returns empty list
    (no cards emitted from closed positions).
    """
    raw_entries = pm.get_leaderboard(limit=top_n)
    if not raw_entries:
        logger.warning("Leaderboard returned no data.")
        return []

    for idx, raw in enumerate(raw_entries[:top_n], start=1):
        _leaderboard_wallet_to_big_wins(raw, idx)
    return []


def scan_open_positions(top_n: int = config.LEADERBOARD_TOP_N) -> list[BigWin]:
    """
    PRIMARY detection: open positions as big-win entry signals.
    Returns BigWin objects with is_open=True, sorted by trade_size descending.
    """
    return scan_open_positions_from_leaderboard(top_n)


def scan_big_wins_for_wallet(wallet: str, display_name: str = "") -> list[BigWin]:
    """
    Stats-only: closed positions for a single wallet. Returns empty list.
    """
    closed = pm.get_user_closed_positions(wallet)
    return []


def scan_big_wins_for_market(market_id: str, top_holders: int = 20) -> list[BigWin]:
    """
    Stats-only: closed positions for market holders. Returns empty list.
    """
    holders = pm.get_market_holders(market_id, limit=top_holders)
    return []


def annotate_wallet_big_wins(stats: WalletStats, big_wins: list[BigWin]) -> WalletStats:
    """Attach big-win count to an existing WalletStats object."""
    stats.big_win_count = len(big_wins)
    if big_wins:
        stats.biggest_win_usdc = max(stats.biggest_win_usdc, big_wins[0].profit_usdc)
    return stats
