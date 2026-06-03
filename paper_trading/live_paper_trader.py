#!/usr/bin/env python3
"""
live_paper_trader.py — Live paper trading daemon
================================================
Watches the Polyshark queue and simulates fills for every new signal
in real-time using CLOB prices. Does NOT execute real orders.

Run: python3 live_paper_trader.py [--paper-only]

Paper ledger: paper_trading/live_ledger.json
"""
import sys, json, time, logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.polymarket_client import get_market
from wallet_profiles import load_profiles
from paper_trading.config import (
    SLIPPAGE_BUFFER, MAX_CONCURRENT_TRADES, MAX_LOSS_PER_TRADE,
    DAILY_LOSS_CAP, PAPER_LEDGER_FILE, ENTRY_MODE
)
from paper_trading.paper_trading_engine import PaperLedger

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
log = logging.getLogger(__name__)


LEDGER_FILE = Path(PAPER_LEDGER_FILE)
LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)


class LivePaperTrader:
    """Real-time paper trader — mirrors live queue signals."""

    def __init__(self):
        self.ledger = self._load_ledger()
        self.profiles = load_profiles()
        self.last_seen_keys = set()

    def _load_ledger(self) -> PaperLedger:
        if LEDGER_FILE.exists():
            try:
                data = json.loads(LEDGER_FILE.read_text())
                # Reconstruct positions from closed log
                ledger = PaperLedger()
                for entry in data.get('closed', []):
                    ledger.closed.append(entry)
                ledger.total_pnl = sum(e.get('realized_pnl', 0) for e in ledger.closed)
                ledger.wins = sum(1 for e in ledger.closed if e.get('realized_pnl', 0) > 0)
                ledger.losses = sum(1 for e in ledger.closed if e.get('realized_pnl', 0) < 0)
                log.info(f"Loaded ledger: {len(ledger.closed)} closed trades | P&L=${ledger.total_pnl:,.2f}")
                return ledger
            except Exception as e:
                log.warning(f"Could not load ledger: {e}")
        return PaperLedger()

    def _save_ledger(self):
        data = {
            "closed": self.ledger.closed,
            "total_pnl": self.ledger.total_pnl,
            "wins": self.ledger.wins,
            "losses": self.ledger.losses,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        LEDGER_FILE.write_text(json.dumps(data, indent=2))

    def simulate_fill(self, item: dict) -> dict:
        """
        Simulate a fill for a queue item signal.
        Returns fill result dict.
        """
        market_id = item.get('market_id', '')
        wallet    = item.get('wallet', '')
        entry_px  = float(item.get('avg_price', 0) or 0) * 100  # cents
        size_usd  = float(item.get('trade_size_usdc', 0) or 0)
        question  = item.get('question', '')[:80]
        outcome   = item.get('outcome', 'YES')
        ts        = int(item.get('timestamp', 0) or 0)
        geo       = item.get('geo_available', 'UNKNOWN')

        if entry_px == 0 or size_usd == 0:
            return {"status": "skipped", "reason": "zero price or size"}

        # Check concurrent trade cap
        if self.ledger.open_count >= MAX_CONCURRENT_TRADES:
            return {"status": "skipped", "reason": "max concurrent trades reached"}

        side = "YES" if outcome.upper() not in ("DOWN","NO","0") else "NO"
        shares = size_usd / (entry_px / 100)
        filled_px = entry_px * (1 + SLIPPAGE_BUFFER)
        cost = shares * (filled_px / 100)

        signal_id = f"{market_id[:20]}_{wallet[:10]}_{ts}"

        # Get live CLOB price for current market
        live_price_cents = None
        try:
            info = get_market(market_id)
            if info:
                tokens = info.get('tokens', []) or []
                for t in tokens:
                    p = float(t.get('price', 0) or 0) * 100  # convert to cents
                    o = str(t.get('outcome', '') or '')
                    if side == "YES" and o == outcome:
                        live_price_cents = p
                    elif side == "NO" and o == outcome:
                        live_price_cents = p
        except Exception as e:
            log.warning(f"CLOB price fetch failed: {e}")

        # Determine exit price (use live CLOB price for open, or entry for resolved)
        is_open = entry_px < 100.0  # < $1.00 = not resolved
        if is_open and live_price_cents is not None:
            exit_px = live_price_cents
        else:
            exit_px = 100.0 if entry_px >= 100.0 else entry_px  # resolved → $1.00

        # Calculate P&L
        if side == "YES":
            pnl = (exit_px - filled_px) / 100 * shares
        else:
            pnl = (filled_px - exit_px) / 100 * shares

        result = {
            "status": "filled",
            "signal_id": signal_id,
            "market_id": market_id,
            "question": question,
            "wallet": wallet,
            "outcome": outcome,
            "side": side,
            "entry_price": entry_px,
            "filled_price": round(filled_px, 4),
            "exit_price": exit_px,
            "size_usd": round(size_usd, 2),
            "realized_pnl": round(pnl, 2),
            "geo": geo,
            "live_price_cents": live_price_cents,
            "is_open": is_open,
            "ts": ts,
        }

        # Record in ledger
        self.ledger.closed.append({
            "signal_id": signal_id,
            "market_id": market_id,
            "question": question,
            "wallet": wallet,
            "outcome": outcome,
            "side": side,
            "entry_price": round(entry_px, 4),
            "exit_price": exit_px,
            "filled_price": round(filled_px, 4),
            "size_usd": round(size_usd, 2),
            "realized_pnl": round(pnl, 2),
            "geo": geo,
            "live_price_cents": live_price_cents,
            "is_open": is_open,
            "open_ts": ts,
            "close_ts": datetime.now(timezone.utc).timestamp(),
            "exit_reason": "live_c模拟" if is_open else "resolve",
        })
        self.ledger.total_pnl += pnl
        if pnl > 0:
            self.ledger.wins += 1
        else:
            self.ledger.losses += 1

        self._save_ledger()
        return result

    def run_live(self, poll_interval: int = 120):
        """Watch queue and simulate every new signal."""
        from pathlib import Path as P
        QUEUE_FILE = P('/tmp/polyshark_router_queue.json')

        log.info(f"Live paper trader started | poll_interval={poll_interval}s")
        log.info(f"Paper ledger: {LEDGER_FILE}")

        while True:
            try:
                if not QUEUE_FILE.exists():
                    time.sleep(poll_interval)
                    continue

                queue = json.loads(QUEUE_FILE.read_text())
                seen_keys = {f"{i.get('market_id','')}_{i.get('wallet','')}" for i in queue}

                new_items = [i for i in queue if f"{i.get('market_id')}_{i.get('wallet')}" not in self.last_seen_keys]

                if new_items:
                    log.info(f"New signals detected: {len(new_items)}")

                for item in new_items:
                    result = self.simulate_fill(item)
                    if result['status'] == 'filled':
                        pnl = result['realized_pnl']
                        emoji = "🟢" if pnl >= 0 else "🔴"
                        log.info(f"  {emoji} PAPER FILL | {result['question'][:50]} | P&L=${pnl:,.2f}")
                    else:
                        log.info(f"  ⏭ {result['status']}: {result.get('reason','')}")

                self.last_seen_keys = seen_keys

            except Exception as e:
                log.error(f"Live trader error: {e}")

            time.sleep(poll_interval)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--interval', type=int, default=120, help='Poll interval seconds')
    args = parser.parse_args()

    trader = LivePaperTrader()
    trader.run_live(poll_interval=args.interval)