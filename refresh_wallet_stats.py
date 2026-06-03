#!/usr/bin/env python3
"""
Daily wallet stats refresh — run from cron.
Updates all tracked wallets with fresh Polymarket stats.
Keeps wallet_tracker.db and wallet_profiles.json current without manual backfill.
"""
import sqlite3, time, sys, logging
from pathlib import Path
sys.path.insert(0, '/home/ubuntu/.openclaw/workspace/repos/whaletrax')
from src import polymarket_client as pm
from wallet_profiles import update_profile, load_profiles, save_profiles, get_profile

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('wallet_refresh')

DB = Path('/home/ubuntu/.openclaw/workspace/repos/whaletrax/wallet_tracker.db')
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
wallets = [(r['wallet_address'],) for r in conn.execute('SELECT wallet_address FROM tracked_wallets WHERE is_active=1')]
conn.close()
log.info(f'Refreshing {len(wallets)} wallets...')
updated = skipped = errors = 0
for i, (w,) in enumerate(wallets, 1):
    try:
        # Force-refresh via API
        prof = get_profile(w, min_fresh=True)
        closed = pm.get_user_closed_positions(w, limit=5000)
        if not closed:
            skipped += 1
            continue
        p = update_profile(w, '', closed)
        conn = sqlite3.connect(DB)
        conn.execute('''UPDATE tracked_wallets SET
            total_trades=?, total_pnl=?, win_rate_pct=?, win_rate_30d=?, pnl_30d=?,
            streak_current=?, streak_best=?, last_seen=unixepoch(), is_active=1
            WHERE wallet_address=?''',
            (p.total_positions, p.total_pnl, p.win_rate, p.win_rate_30d,
             getattr(p,'pnl_30d',0), p.current_streak, p.longest_streak, w))
        conn.commit(); conn.close()
        updated += 1
        if i % 50 == 0:
            log.info(f'  [{i}/{len(wallets)}] updated={updated} skipped={skipped} errors={errors}')
        time.sleep(0.1)
    except Exception as e:
        errors += 1
        if errors <= 3:
            log.warning(f'  Error {w[:16]}: {e}')
save_profiles(load_profiles())
log.info(f'DONE — updated={updated} skipped={skipped} errors={errors}')