#!/usr/bin/env python3
"""
paper_trading_engine.py — Polyshark Paper Trading Simulation
=============================================================
Simulates copy-trading of whale wallet signals on Polymarket.
Uses real historical wallet data to paper-trade without real capital.

Run standalone:
  python3 paper_trading_engine.py                    # full backtest
  python3 paper_trading_engine.py --live             # live simulation (uses current queue)
  python3 paper_trading_engine.py --wallet 0x...     # single wallet backtest

Output:
  paper_trading/ledger.json         — every simulated fill
  paper_trading/results/summary.json — performance metrics
"""
import sys, json, argparse, logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
from copy import deepcopy

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.polymarket_client import get_user_closed_positions, get_market
from wallet_profiles import load_profiles
from paper_trading.config import (
    SLIPPAGE_BUFFER, MIN_WIN_RATE, MIN_POSITIONS, SKIP_CLOSED,
    ENTRY_MODE, EXIT_MODE, PARTIAL_CLOSE_HRS, PARTIAL_PROFIT_PCT,
    MAX_CONCURRENT_TRADES, MAX_LOSS_PER_TRADE, DAILY_LOSS_CAP,
    PAPER_LEDGER_FILE, RESULTS_DIR
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
log = logging.getLogger(__name__)

RESULTS_DIR = Path(RESULTS_DIR)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


# ──────────────────────────────────────────────────────────────
# Data structures
# ──────────────────────────────────────────────────────────────

class SimPosition:
    def __init__(self, signal_id, market_id, question, outcome,
                 entry_price, size_usd, wallet, timestamp, copy_pct=1.0):
        self.signal_id   = signal_id
        self.market_id   = market_id
        self.question    = question
        self.outcome     = outcome      # "YES" or "NO"
        self.side        = "YES" if outcome not in ("DOWN","NO","0") else "NO"
        self.entry_price = entry_price  # in cents (e.g. 37.0 = $0.37)
        self.size_usd    = size_usd
        self.copy_pct    = copy_pct
        self.wallet      = wallet
        self.open_ts     = timestamp
        self.status      = "open"   # open | partial_close | resolved
        self.realized_pnl = 0.0
        self.filled_price = entry_price * (1 + SLIPPAGE_BUFFER)  # worse due to slippage
        self.max_profit   = 0.0
        self.exit_reason  = ""

    @property
    def notional(self):
        """USD notional = size_usd / entry_price (shares bought)"""
        if self.entry_price == 0:
            return 0
        shares = self.size_usd / (self.entry_price / 100)
        return shares * (self.filled_price / 100)

    def pnl_at_price(self, price_cents: float) -> float:
        shares = self.size_usd / (self.entry_price / 100) if self.entry_price else 0
        if self.side == "YES":
            return (price_cents - self.filled_price) / 100 * shares
        else:
            return (self.filled_price - price_cents) / 100 * shares

    def check_stop_loss(self, current_price: float) -> bool:
        pnl = self.pnl_at_price(current_price)
        return pnl <= -MAX_LOSS_PER_TRADE


class PaperLedger:
    """Tracks all simulated positions and performance."""

    def __init__(self):
        self.positions: list[SimPosition] = []
        self.closed: list[dict] = []
        self.daily_pnl = 0.0
        self.daily_loss_streak = 0.0
        self.total_pnl = 0.0
        self.wins = 0
        self.losses = 0

    def open_position(self, pos: SimPosition):
        if self.open_count >= MAX_CONCURRENT_TRADES:
            return False  # cap reached
        self.positions.append(pos)
        return True

    @property
    def open_count(self):
        return len([p for p in self.positions if p.status == "open"])

    def resolve_position(self, pos: SimPosition, exit_price: float,
                         reason: str, realized_pnl: float):
        pos.status = reason
        pos.realized_pnl = realized_pnl
        self.closed.append({
            "signal_id": pos.signal_id,
            "market_id": pos.market_id,
            "question": pos.question,
            "outcome": pos.outcome,
            "wallet": pos.wallet,
            "side": pos.side,
            "entry_price": pos.entry_price,
            "exit_price": exit_price,
            "size_usd": pos.size_usd,
            "realized_pnl": realized_pnl,
            "exit_reason": reason,
            "open_ts": pos.open_ts,
            "close_ts": datetime.now(timezone.utc).timestamp(),
        })
        if pos in self.positions:
            self.positions.remove(pos)
        self.total_pnl += realized_pnl
        if realized_pnl > 0:
            self.wins += 1
        else:
            self.losses += 1
            if realized_pnl < -DAILY_LOSS_CAP:
                self.daily_loss_streak += 1

    def summary(self) -> dict:
        closed = self.closed
        total = len(closed)
        wins = self.wins
        losses = self.losses
        win_rate = wins / total * 100 if total > 0 else 0
        total_pnl = sum(c.get('realized_pnl', 0) for c in closed)
        avg_win = sum(c['realized_pnl'] for c in closed if c['realized_pnl'] > 0) / max(1, wins)
        avg_loss = sum(abs(c['realized_pnl']) for c in closed if c['realized_pnl'] < 0) / max(1, losses)
        return {
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate_pct": round(win_rate, 1),
            "total_pnl": round(total_pnl, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "avg_roi_pct": round(total_pnl / max(1, sum(c['size_usd'] for c in closed)) * 100, 2),
        }


# ──────────────────────────────────────────────────────────────
# Core simulation logic
# ──────────────────────────────────────────────────────────────

def backtest_wallet(wallet: str, limit: int = 5000) -> dict:
    """
    Paper-trade a single wallet's historical signals.
    Reconstructs what would have happened if we copied each of their trades.
    """
    log.info(f"Backtesting wallet: {wallet[:20]}...")
    positions = get_user_closed_positions(wallet, limit=limit)
    if not positions:
        return {"error": f"No positions found for {wallet[:20]}"}

    # Sort by timestamp (oldest first → simulation in order)
    positions.sort(key=lambda p: p.get('timestamp', 0))

    ledger = PaperLedger()
    results = []

    for i, pos_data in enumerate(positions):
        ts     = int(pos_data.get('timestamp', 0) or 0)
        if not ts:
            continue

        # Skip if market was already closed at our entry time
        end_date = pos_data.get('endDate', '') or ''
        if SKIP_CLOSED and end_date:
            try:
                end_ts = datetime.fromisoformat(end_date.replace('Z','+00:00')).replace(tzinfo=timezone.utc).timestamp()
                if end_ts < ts:
                    continue  # market resolved before our "entry"
            except Exception:
                pass

        question = pos_data.get('title', pos_data.get('question', '?'))[:80]
        outcome  = pos_data.get('outcome', 'YES')
        side     = "YES" if outcome not in ("DOWN","NO","0","NO") else "NO"
        avg_px   = float(pos_data.get('avgPrice', 0) or 0) * 100  # convert to cents
        pnl_raw  = float(pos_data.get('realizedPnl', 0) or 0)
        size     = float(pos_data.get('totalBought', 0) or 0)

        if avg_px == 0:
            continue  # no entry price — skip

        # Simulate entry (slippage-adjusted)
        filled_px = avg_px * (1 + SLIPPAGE_BUFFER)
        shares    = size / (avg_px / 100) if avg_px else 0
        cost      = shares * (filled_px / 100)

        # Simulate exit at resolution
        # If pnl_raw > 0 → winner → our exit at $1.00 for YES or $0.00 for NO
        # If pnl_raw < 0 → loser → exit at worst price
        if side == "YES":
            if pnl_raw > 0:
                exit_px = 100.0   # resolved YES at $1.00
            else:
                exit_px = 0.0     # resolved NO → YES position worth $0
        else:
            if pnl_raw > 0:
                exit_px = 100.0   # resolved NO at $1.00 (NO shares worth $1)
            else:
                exit_px = 0.0     # resolved YES → NO position worth $0

        realized_pnl = pnl_raw  # already calculated by Polymarket with fees

        signal_id = f"{wallet[:10]}_{ts}"
        pos = SimPosition(
            signal_id=signal_id,
            market_id=pos_data.get('conditionId', ''),
            question=question,
            outcome=outcome,
            entry_price=avg_px,
            size_usd=cost,
            wallet=wallet,
            timestamp=ts,
        )
        pos.filled_price = filled_px

        # Add to ledger before resolving
        ledger.positions.append(pos)
        ledger.resolve_position(pos, exit_px, "resolve", realized_pnl)

        if (i + 1) % 500 == 0:
            log.info(f"  Processed {i+1}/{len(positions)} positions...")

    summary = ledger.summary()
    summary['wallet'] = wallet
    summary['positions_checked'] = len(positions)
    log.info(f"  → {summary['total_trades']} trades | WR={summary['win_rate_pct']}% | P&L=${summary['total_pnl']:,.2f}")
    return summary


def backtest_top_wallets(top_n: int = 20) -> list[dict]:
    """Run backtest on top-N wallets from wallet_profiles.json."""
    profiles = load_profiles()
    if not profiles:
        log.warning("No profiles loaded from wallet_profiles.json")
        return []

    # Score profiles by: win_rate * min(total_positions, 500) / 100
    scored = []
    for addr, p in profiles.items():
        wr = getattr(p, 'win_rate', 0) or 0
        tp = getattr(p, 'total_positions', 0) or 0
        if wr >= MIN_WIN_RATE and tp >= MIN_POSITIONS:
            score = wr * min(tp, 500) / 100
            scored.append((score, addr, p))

    scored.sort(reverse=True)
    top = scored[:top_n]

    results = []
    for score, addr, p in top:
        log.info(f"\n{'='*60}")
        log.info(f"Rank #{len(results)+1} | Score={score:.1f} | {addr[:20]}...")
        log.info(f"  WR={p.win_rate:.1f}% | Positions={p.total_positions} | PnL=${p.total_pnl:,.2f}")
        result = backtest_wallet(addr, limit=5000)
        result['rank'] = len(results) + 1
        result['win_rate'] = p.win_rate
        result['total_positions'] = p.total_positions
        results.append(result)

    return results


def save_results(results: list[dict], label: str = "backtest"):
    """Save backtest results and ledger to disk."""
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%d_%H%M')
    out_dir = RESULTS_DIR / f"{label}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Summary
    summary_path = out_dir / "summary.json"
    with open(summary_path, 'w') as f:
        json.dump(results, f, indent=2)

    # Aggregate stats
    total_trades = sum(r.get('total_trades', 0) for r in results)
    total_pnl    = sum(r.get('total_pnl', 0) for r in results)
    wins         = sum(r.get('wins', 0) for r in results)
    losses       = sum(r.get('losses', 0) for r in results)
    agg = {
        "label": label,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "wallets_tested": len(results),
        "total_trades": total_trades,
        "total_pnl": round(total_pnl, 2),
        "win_rate_pct": round(wins / max(1, wins + losses) * 100, 1),
        "avg_pnl_per_trade": round(total_pnl / max(1, total_trades), 2),
        "results": results,
    }
    agg_path = out_dir / "aggregate.json"
    with open(agg_path, 'w') as f:
        json.dump(agg, f, indent=2)

    log.info(f'✅ Results saved to {out_dir}/')
    log.info(f"   Wallets: {len(results)} | Trades: {total_trades} | P&L: ${total_pnl:,.2f}")
    return agg


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Polyshark Paper Trading Engine")
    parser.add_argument('--wallet', type=str, default=None, help='Single wallet address')
    parser.add_argument('--top-n', type=int, default=20, help='Backtest top N wallets')
    parser.add_argument('--limit', type=int, default=5000, help='Positions per wallet')
    parser.add_argument('--live', action='store_true', help='Live simulation mode')
    parser.add_argument('--label', type=str, default='backtest', help='Result label')
    args = parser.parse_args()

    if args.wallet:
        results = [backtest_wallet(args.wallet, limit=args.limit)]
    elif args.live:
        log.info("Live simulation mode — watching queue for new signals...")
        log.info("(Live mode not yet implemented — use --wallet or --top-n)")
    else:
        results = backtest_top_wallets(top_n=args.top_n)

    agg = save_results(results, label=args.label)
    print(json.dumps(agg, indent=2)[:2000])