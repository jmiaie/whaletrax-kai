#!/usr/bin/env python3
"""
Polyshark Subscription Manager
Handles subscriber records, tier tracking, expiry, and auto-pay status.
SQLite backend - single file, no server needed.
"""

import sqlite3, json, logging, datetime
from pathlib import Path

DB_PATH = Path('/home/ubuntu/.openclaw/workspace/polyshark_subs.db')
LOG_FILE = Path('/tmp/polyshark_subs.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s',
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()]
)
log = logging.getLogger('polyshark_subs')

# ── Tier Definitions ─────────────────────────────────────────────────────────
TIER_ALL_CHANNELS = {'pro_lifetime', 'pro_annual', 'pro_monthly', 'admin', 'founding_shark'}
TIER_SINGLE_CHANNEL = {'channel_annual', 'channel_monthly'}

TIER_PRICES = {
    175000: 'pro_lifetime',
    52800:  'pro_annual',
    33600:  'channel_annual',
    5500:   'pro_monthly',
    3500:   'channel_monthly',
}

CHANNELS = {
    'polyshark':   -1003999194095,
    'hub':         -1003739747776,
    'sports':      -1003948034686,
    'crypto':      -1003999731708,
    'weather':     -1003532326443,
    'world':       -1003927756388,
    'politics':    -1003935178097,
    'econ':        -1003868008293,
    'chat':        -1003860830659,
}

TIER_CHANNELS = {
    'pro_lifetime':    list(CHANNELS.values()),
    'pro_annual':      list(CHANNELS.values()),
    'pro_monthly':     list(CHANNELS.values()),
    'channel_annual': [],
    'channel_monthly':[],
    'founding_shark':  list(CHANNELS.values()),
    'admin':           list(CHANNELS.values()),
}

def tier_from_price(cents):
    return TIER_PRICES.get(cents, 'pro_monthly')

def is_all_channels(tier):
    return tier in TIER_ALL_CHANNELS

def is_single_channel(tier):
    return tier in TIER_SINGLE_CHANNEL

SCHEMA = '''
CREATE TABLE IF NOT EXISTS subscribers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT UNIQUE NOT NULL,
    email TEXT,
    tier TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    auto_pay INTEGER NOT NULL DEFAULT 0,
    payment_method TEXT,
    expires_at TEXT,
    subscribed_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS channel_access (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    granted_at TEXT NOT NULL,
    UNIQUE(user_id, channel)
);
'''

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn

def add_subscriber(tg_id, email, tier, source='manual', auto_pay=False, channel_category=None):
    conn = get_db()
    now = datetime.datetime.utcnow()
    expires = None
    if tier in TIER_ALL_CHANNELS.union(TIER_SINGLE_CHANNEL):
        if 'annual' in tier:
            expires = (now + datetime.timedelta(days=365)).isoformat()
        elif 'monthly' in tier:
            expires = (now + datetime.timedelta(days=30)).isoformat()
    cur = conn.execute(
        'SELECT id FROM subscribers WHERE user_id = ?', (tg_id,)
    )
    row = cur.fetchone()
    if row:
        conn.execute(
            "UPDATE subscribers SET tier=?, status='active', expires_at=?, updated_at=? WHERE user_id=?",
            (tier, expires, now.isoformat(), tg_id)
        )
    else:
        conn.execute(
            "INSERT INTO subscribers (user_id, email, tier, status, subscribed_at, expires_at) VALUES (?, ?, ?, 'active', ?, ?)",
            (tg_id, email, tier, now.isoformat(), expires)
        )
    conn.commit()
    grant_channels(tg_id, tier, channel_category)
    log.info(f"Subscriber added: {tg_id} tier={tier} expires={expires}")

def grant_channels(tg_id, tier, channel_category=None):
    if tier not in TIER_CHANNELS:
        return
    channels = TIER_CHANNELS[tier]
    conn = get_db()
    for cid in channels:
        conn.execute(
            "INSERT OR IGNORE INTO channel_access (user_id, channel, granted_at) VALUES (?, ?, ?)",
            (tg_id, str(cid), datetime.datetime.utcnow().isoformat())
        )
    conn.commit()

def get_subscriber(tg_id):
    conn = get_db()
    row = conn.execute('SELECT * FROM subscribers WHERE user_id = ?', [tg_id]).fetchone()
    conn.close()
    return dict(row) if row else None

def get_all_subscribers(status=None):
    conn = get_db()
    if status:
        rows = conn.execute('SELECT * FROM subscribers WHERE status = ? ORDER BY expires_at ASC', [status]).fetchall()
    else:
        rows = conn.execute('SELECT * FROM subscribers ORDER BY expires_at ASC').fetchall()
    conn.close()
    return [dict(r) for r in rows]

def set_status(tg_id, status):
    conn = get_db()
    now = datetime.datetime.utcnow().isoformat()
    conn.execute('UPDATE subscribers SET status=?, updated_at=? WHERE user_id=?', [status, now, tg_id])
    conn.commit()
    conn.close()

if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--add', nargs=4, metavar=('TG_ID', 'EMAIL', 'TIER', 'SOURCE'))
    p.add_argument('--list', action='store_true')
    p.add_argument('--check', action='store_true')
    args = p.parse_args()
    if args.add:
        add_subscriber(*args.add)
        print('Added:', args.add[0])
    elif args.list:
        for s in get_all_subscribers():
            print(s['user_id'], s['tier'], s['status'])
    elif args.check:
        print('Expiry check not yet ported')