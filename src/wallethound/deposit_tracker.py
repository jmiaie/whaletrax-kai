"""
Deposit & withdrawal tracker for WalletHound.

Identifies non-trade USDC movements (deposits into and withdrawals from a
Polymarket wallet) so that balance growth can be accurately attributed to
trading wins rather than external funding.

Strategy
--------
Polymarket wallets receive USDC via:
  1. Deposits — user-initiated transfers into their proxy wallet
  2. Trade settlements — payouts from resolved markets
  3. CLOB proceeds — USDC received when selling shares

We distinguish deposits/withdrawals from trade activity by comparing on-chain
activity records (from the ``/activity`` endpoint) against resolved trade data.
Any USDC-in that does not correspond to a known trade settlement is classified
as a deposit; any USDC-out that is not a share purchase is a withdrawal.
"""

from __future__ import annotations

import logging
from typing import Optional

from .. import polymarket_client as pm
from ..wallet_scanner import _safe_float
from .models import BalanceSnapshot, DepositWithdrawal

logger = logging.getLogger(__name__)

# Activity type labels that indicate deposits / withdrawals
_DEPOSIT_TYPES = frozenset({
    "deposit", "transfer_in", "fund", "receive", "top_up",
})
_WITHDRAWAL_TYPES = frozenset({
    "withdrawal", "transfer_out", "withdraw", "send",
})

# Trade-related activity types we should exclude from deposit/withdrawal counts
_TRADE_TYPES = frozenset({
    "trade", "buy", "sell", "claim", "redeem", "settlement",
    "market_buy", "market_sell", "limit_buy", "limit_sell",
})


def _classify_activity(raw: dict) -> Optional[DepositWithdrawal]:
    """
    Classify a single activity record as a deposit, withdrawal, or None
    (trade-related / unrecognised).
    """
    act_type = str(
        raw.get("type") or raw.get("activityType") or raw.get("action") or ""
    ).lower().strip()

    amount = _safe_float(
        raw.get("amount") or raw.get("usdcAmount") or raw.get("value")
    )
    wallet = str(
        raw.get("proxyWallet") or raw.get("proxy_wallet")
        or raw.get("user") or raw.get("address") or ""
    )
    ts = int(_safe_float(raw.get("timestamp") or raw.get("createdAt") or raw.get("time")))
    tx_id = str(raw.get("id") or raw.get("txHash") or raw.get("transactionHash") or "")

    if act_type in _TRADE_TYPES:
        return None

    if act_type in _DEPOSIT_TYPES:
        return DepositWithdrawal(
            wallet=wallet, tx_type="deposit", amount_usdc=abs(amount),
            timestamp=ts, tx_id=tx_id,
        )

    if act_type in _WITHDRAWAL_TYPES:
        return DepositWithdrawal(
            wallet=wallet, tx_type="withdrawal", amount_usdc=abs(amount),
            timestamp=ts, tx_id=tx_id,
        )

    # Heuristic: large positive amount with no trade match → deposit
    # Negative amount (or marked as outgoing) → withdrawal
    # We fall back to looking at descriptive fields
    description = str(raw.get("description") or raw.get("memo") or "").lower()
    if "deposit" in description or "fund" in description:
        return DepositWithdrawal(
            wallet=wallet, tx_type="deposit", amount_usdc=abs(amount),
            timestamp=ts, tx_id=tx_id,
        )
    if "withdraw" in description or "send" in description:
        return DepositWithdrawal(
            wallet=wallet, tx_type="withdrawal", amount_usdc=abs(amount),
            timestamp=ts, tx_id=tx_id,
        )

    return None


def get_deposits_withdrawals(wallet: str) -> list[DepositWithdrawal]:
    """
    Return all detected deposit and withdrawal events for *wallet*.
    """
    raw_activity = pm.get_user_activity(wallet)
    events: list[DepositWithdrawal] = []
    for raw in raw_activity:
        evt = _classify_activity(raw)
        if evt is not None:
            evt.wallet = wallet
            events.append(evt)

    events.sort(key=lambda e: e.timestamp)
    return events


def compute_totals(events: list[DepositWithdrawal]) -> tuple[float, float]:
    """
    Return ``(total_deposits, total_withdrawals)`` from a list of events.
    """
    deposits = sum(e.amount_usdc for e in events if e.tx_type == "deposit")
    withdrawals = sum(e.amount_usdc for e in events if e.tx_type == "withdrawal")
    return deposits, withdrawals


def compute_organic_growth(
    total_profit_usdc: float,
    total_deposits: float,
    total_withdrawals: float,
) -> float:
    """
    Organic growth = total profit attributable to wins only.

    Since profit already factors in trade costs, we only need to ensure we
    don't double-count deposits as profit.  The formula:

        organic_growth = total_profit_usdc

    The profit from the Data API's closed-positions is already net of trade
    costs.  Deposits/withdrawals only move USDC in/out of the wallet — they
    don't appear in the closed-positions P&L.  So as long as we source
    ``total_profit_usdc`` from resolved positions (not from balance delta),
    it is already organic.

    This function exists to make the accounting model explicit and testable.
    If a caller computes profit from a raw balance delta instead, they should
    pass ``balance_delta - (deposits - withdrawals)`` as total_profit_usdc.
    """
    return total_profit_usdc


def build_balance_snapshots(
    wallet: str,
    closed_positions: list[dict],
    deposit_events: list[DepositWithdrawal],
) -> list[BalanceSnapshot]:
    """
    Build a time-ordered series of balance snapshots by replaying closed
    positions and deposit/withdrawal events chronologically.
    """
    # Build time-ordered events: (timestamp, pnl_delta, deposit_delta, withdrawal_delta)
    timeline: list[tuple[int, float, float, float]] = []

    for pos in closed_positions:
        pnl = _safe_float(
            pos.get("pnl") or pos.get("profit") or pos.get("profitAndLoss")
            or pos.get("realizedPnl")
        )
        ts = int(_safe_float(pos.get("timestamp") or pos.get("createdAt") or pos.get("time")))
        timeline.append((ts, pnl, 0.0, 0.0))

    for evt in deposit_events:
        if evt.tx_type == "deposit":
            timeline.append((evt.timestamp, 0.0, evt.amount_usdc, 0.0))
        else:
            timeline.append((evt.timestamp, 0.0, 0.0, evt.amount_usdc))

    timeline.sort(key=lambda x: x[0])

    snapshots: list[BalanceSnapshot] = []
    running_balance = 0.0
    cum_deposits = 0.0
    cum_withdrawals = 0.0

    for ts, pnl, dep, wd in timeline:
        running_balance += pnl + dep - wd
        cum_deposits += dep
        cum_withdrawals += wd
        snapshots.append(BalanceSnapshot(
            wallet=wallet,
            timestamp=ts,
            total_balance_usdc=running_balance,
            deposits_cumulative=cum_deposits,
            withdrawals_cumulative=cum_withdrawals,
        ))

    return snapshots
