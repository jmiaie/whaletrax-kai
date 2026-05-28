#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, '/home/ubuntu/.openclaw/workspace/repos/whaletrax')
from src import polymarket_client as pm
from src.parsers import parse_leaderboard_entry
from wallet_profiles import WalletProfile, save_profiles, load_profiles

RESUME_LOG = Path('/tmp/whaletrax_backfill_progress.json')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', type=int, default=1)
    ap.add_argument('--count', type=int, default=40)
    args = ap.parse_args()

    raw_entries = pm.get_leaderboard(limit=args.start + args.count - 1)
    selected = raw_entries[args.start-1:args.start-1+args.count]

    profiles = load_profiles()
    updated = 0
    closed_total = 0
    RESUME_LOG.write_text(json.dumps({'start': args.start, 'count': args.count, 'status': 'running'}))

    for idx, raw in enumerate(selected, start=args.start):
        entry = parse_leaderboard_entry(raw, idx)
        if not entry.proxy_wallet:
            continue
        closed = pm.get_user_closed_positions(entry.proxy_wallet)
        if not closed:
            continue
        p = profiles.get(entry.proxy_wallet.lower()) or WalletProfile(entry.proxy_wallet, entry.name)
        p.name = entry.name or p.name
        p.merge_positions(closed)
        profiles[entry.proxy_wallet.lower()] = p
        updated += 1
        closed_total += len(closed)
        print(f'{idx}: {entry.proxy_wallet} closed={len(closed)}')

    save_profiles(profiles)
    RESUME_LOG.write_text(json.dumps({'start': args.start, 'count': args.count, 'status': 'done', 'updated_wallets': updated, 'closed_positions': closed_total}))
    print(json.dumps({'updated_wallets': updated, 'closed_positions': closed_total}))

if __name__ == '__main__':
    main()
