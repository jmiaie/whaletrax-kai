#!/usr/bin/env python3
"""
Backfill wallet profiles from wallet_tracker.db.
For closed trades: compute real win_rate and streak from realized_pnl.
For open trades (is_closed=0): add as positions but flag that they're unresolved.
"""
import sys, sqlite3, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from wallet_profiles import update_profile, load_profiles

DB_PATH = Path(__file__).parent / 'wallet_tracker.db'
PROFILE_FILE = Path('/tmp/wallet_profiles.json')


def backfill():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row

    cur = db.execute('''
        SELECT wallet_address, trade_id, market_id, market_question,
               side, outcome, entry_price, size_usdc, realized_pnl,
               ts_enter, ts_exit, ts_created, is_closed
        FROM wallet_trades
        ORDER BY wallet_address, ts_exit ASC
    ''')

    by_wallet = {}
    for row in cur:
        wa = row['wallet_address'].lower()
        by_wallet.setdefault(wa, []).append({
            'id':          row['trade_id'],
            'trade_id':    row['trade_id'],
            'market_id':   row['market_id'],
            'side':        row['side'],
            'outcome':     row['outcome'],
            'entry_price': float(row['entry_price'] or 0),
            'size':        float(row['size_usdc'] or 0),
            'realizedPnl': float(row['realized_pnl'] or 0),
            'roiPct':      0.0,
            'timestamp':   int(row['ts_exit'] or row['ts_enter'] or 0),
            'is_closed':   row['is_closed'],
            'is_win':      bool(row['is_closed'] == 1 and row['realized_pnl'] > 0),
        })

    closed = sum(1 for w in by_wallet.values() for p in w if p['is_closed'] == 1)
    open_ = sum(1 for w in by_wallet.values() for p in w if p['is_closed'] == 0)
    print(f"Processing {len(by_wallet)} wallets — {closed} closed, {open_} open trades")

    updated = 0
    for wallet, positions in by_wallet.items():
        closed_pos = [p for p in positions if p['is_closed'] == 1]
        if not closed_pos:
            continue
        try:
            p = update_profile(wallet, '', closed_pos)
            stats = ws.scan_wallet(wallet)
            total_trades = stats.total_trades or p.total_positions
            total_pnl = stats.total_profit_usdc if stats.total_profit_usdc is not None else p.total_pnl
            win_rate = stats.win_rate_pct if stats.win_rate_pct is not None else p.win_rate
            roi_30d = stats.avg_roi_pct if stats.avg_roi_pct is not None else 0
            db.execute(
                '''UPDATE tracked_wallets
                   SET total_trades=?, total_pnl=?, win_rate_pct=?, roi_pct=?, roi_30d=?,
                       display_name=COALESCE(NULLIF(display_name,''), ?),
                       last_seen=unixepoch(), is_active=1
                   WHERE lower(wallet_address)=?''',
                (total_trades, total_pnl, win_rate, roi_30d, roi_30d, p.display_name or '', wallet)
            )
            db.commit()
            print(f"  {wallet[:14]}... | {total_trades} closed | {win_rate:.1f}% WR | streak={p.current_streak} | PnL=${total_pnl:,.0f}")
            updated += 1
        except Exception as e:
            print(f"  ERROR {wallet[:14]}...: {e}")

    profiles = load_profiles()
    with_trades = [w for w, p in profiles.items() if p.total_positions > 0]
    print(f"\n=== Backfill Complete ===")
    print(f"Wallets with closed trades: {updated}")
    print(f"Profiles with data: {len(with_trades)} / {len(profiles)}")
    print(f"File: {PROFILE_FILE}")

    db.close()


if __name__ == '__main__':
    backfill()
