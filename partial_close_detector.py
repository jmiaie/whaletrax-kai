#!/usr/bin/env python3
"""
partial_close_detector.py
Jeff Milam — KaiOC 🌊

Detects early exits / partial closes in whale wallets by monitoring
position size changes in get_user_positions.

DB: own file (partial_close_detector.db) — no conflict with polyshark_router
WALLET_SOURCE: read-only from wallet_tracker.db (tracked_wallets)

ARCHITECTURE:
  - position_latest  : stores the MOST RECENT size per wallet/market (for diffing)
  - position_snapshots : full history (optional, for analytics)
  - partial_close_events : detected shrink events

RUN:
  python3 partial_close_detector.py            # continuous (5-min polls)
  python3 partial_close_detector.py --once     # single poll (cron-friendly)
  python3 partial_close_detector.py --report    # print event report
  python3 partial_close_detector.py --resolve  # run resolution pass only
"""

import sys, os, time, json, sqlite3, logging, argparse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from src import polymarket_client as pm

# ── Config ──────────────────────────────────────────────────────────────────
SNAPSHOT_INTERVAL = 300    # seconds between polls (5 min)
MIN_POSITION_SIZE = 50     # ignore positions < $50 (noise filter)
MIN_SHRINK_PCT    = 5.0    # flag only if size shrank by ≥5%
LOG_FILE          = '/home/ubuntu/.openclaw/workspace/repos/whaletrax/logs/partial_close_detector.log'
DB_PATH           = '/home/ubuntu/.openclaw/workspace/repos/whaletrax/partial_close_detector.db'
WALLET_TRACKER    = '/home/ubuntu/.openclaw/workspace/repos/whaletrax/wallet_tracker.db'

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()],
)
log = logging.getLogger('partial_close')

INIT_SQL = """
CREATE TABLE IF NOT EXISTS position_latest (
    wallet_address  TEXT    NOT NULL,
    market_id      TEXT    NOT NULL,
    slug           TEXT,
    title          TEXT,
    outcome        TEXT,
    side           TEXT,
    size           REAL    NOT NULL,
    avg_price      REAL,
    current_value  REAL,
    cash_pnl       REAL,
    end_date       TEXT,
    redeemable     INTEGER DEFAULT 0,
    ts_snapshot    INTEGER NOT NULL,
    PRIMARY KEY (wallet_address, market_id)
);

CREATE TABLE IF NOT EXISTS position_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address  TEXT    NOT NULL,
    market_id      TEXT    NOT NULL,
    slug           TEXT,
    title          TEXT,
    outcome        TEXT,
    side           TEXT,
    size           REAL    NOT NULL,
    avg_price      REAL,
    current_value  REAL,
    cash_pnl       REAL,
    end_date       TEXT,
    redeemable     INTEGER DEFAULT 0,
    ts_snapshot    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS partial_close_events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address      TEXT    NOT NULL,
    market_id          TEXT    NOT NULL,
    slug               TEXT,
    title              TEXT,
    outcome            TEXT,
    side               TEXT,
    detected_at        INTEGER NOT NULL,
    size_before        REAL    NOT NULL,
    size_after         REAL    NOT NULL,
    shrink_pct         REAL    NOT NULL,
    avg_price          REAL,
    cash_pnl_at_detect REAL,
    end_date           TEXT,
    resolved           INTEGER DEFAULT 0,
    realized_pnl       REAL,
    netOutcome         TEXT,
    resolution_notes   TEXT
);
"""

# ── DB helpers ───────────────────────────────────────────────────────────────

def _db(db_path=DB_PATH, row_factory=False):
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=30000')
    if row_factory:
        conn.row_factory = sqlite3.Row
    return conn

def _retry_write(fn, db_path=DB_PATH, max_retries=8):
    for attempt in range(max_retries):
        try:
            conn = _db(db_path)
            fn(conn)
            conn.commit()
            conn.close()
            return True
        except sqlite3.OperationalError as e:
            if 'locked' in str(e) and attempt < max_retries - 1:
                time.sleep(0.5 * (2 ** attempt))
            else:
                raise
    return False

def init_db():
    c = _db(DB_PATH)
    c.executescript(INIT_SQL)
    c.close()

def get_open_wallets():
    """Read-only from wallet_tracker.db — no locking issue."""
    conn = _db(WALLET_TRACKER)
    rows = conn.execute(
        'SELECT wallet_address FROM tracked_wallets WHERE is_active=1'
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]

def get_prior_size(wallet, market_id):
    """Get last known size from position_latest."""
    c = _db(DB_PATH)
    row = c.execute(
        'SELECT size FROM position_latest WHERE wallet_address=? AND market_id=?',
        (wallet, market_id)
    ).fetchone()
    c.close()
    return row[0] if row else None

def upsert_position(raw, ts_snap):
    """Upsert into position_latest (for fast diffing) + insert history row."""
    wallet    = raw.get('proxyWallet') or raw.get('wallet', '')
    market_id = str(raw.get('conditionId', '') or raw.get('market_id', ''))
    size      = raw.get('size', 0) or 0

    def _do(conn):
        conn.execute('''
            INSERT OR REPLACE INTO position_latest
            (wallet_address, market_id, slug, title, outcome, side, size,
             avg_price, current_value, cash_pnl, end_date, redeemable, ts_snapshot)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            wallet, market_id,
            raw.get('slug', ''), raw.get('title', ''),
            raw.get('outcome', ''), raw.get('outcomeIndex', ''),
            size,
            raw.get('avgPrice', 0) or 0,
            raw.get('currentValue', 0) or 0,
            raw.get('cashPnl', 0) or 0,
            raw.get('endDate', ''),
            1 if raw.get('redeemable') else 0,
            ts_snap,
        ))
        conn.execute('''
            INSERT INTO position_snapshots
            (wallet_address, market_id, slug, title, outcome, side, size,
             avg_price, current_value, cash_pnl, end_date, redeemable, ts_snapshot)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            wallet, market_id,
            raw.get('slug', ''), raw.get('title', ''),
            raw.get('outcome', ''), raw.get('outcomeIndex', ''),
            size,
            raw.get('avgPrice', 0) or 0,
            raw.get('currentValue', 0) or 0,
            raw.get('cashPnl', 0) or 0,
            raw.get('endDate', ''),
            1 if raw.get('redeemable') else 0,
            ts_snap,
        ))
    return _retry_write(_do)

def insert_partial_close(raw, wallet, market_id, detected_at,
                          size_before, size_after, shrink_pct):
    def _do(conn):
        conn.execute('''
            INSERT INTO partial_close_events
            (wallet_address, market_id, slug, title, outcome, side, detected_at,
             size_before, size_after, shrink_pct, avg_price, cash_pnl_at_detect, end_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            wallet, market_id,
            raw.get('slug', ''), raw.get('title', ''),
            raw.get('outcome', ''), raw.get('outcomeIndex', ''),
            detected_at, size_before, size_after, shrink_pct,
            raw.get('avgPrice', 0) or 0,
            raw.get('cashPnl', 0) or 0,
            raw.get('endDate', ''),
        ))
    return _retry_write(_do)

def is_duplicate_recent(wallet, market_id, lookback=3600):
    c = _db(DB_PATH)
    row = c.execute('''
        SELECT 1 FROM partial_close_events
        WHERE wallet_address=? AND market_id=?
          AND detected_at > ?
        LIMIT 1
    ''', (wallet, market_id, int(time.time()) - lookback)).fetchone()
    c.close()
    return row is not None

def resolve_partial_closes():
    c = _db(DB_PATH, row_factory=True)
    events = c.execute(
        'SELECT * FROM partial_close_events WHERE resolved=0'
    ).fetchall()
    c.close()
    if not events:
        return 0

    wallets = list(set(e['wallet_address'] for e in events))
    resolved = 0

    for wallet in wallets:
        try:
            closed = pm.get_user_closed_positions(wallet, limit=200)
        except Exception as e:
            log.warning('resolve [%s]: %s', wallet[:16], e)
            continue

        by_mkt = {str(p.get('conditionId', '') or p.get('slug', '')): p
                  for p in closed}

        def _do(conn):
            nonlocal resolved
            for ev in events:
                if ev['wallet_address'] != wallet:
                    continue
                match = by_mkt.get(ev['market_id']) or by_mkt.get(ev['slug'], {})
                rpnl = match.get('realizedPnl')
                if rpnl is not None and rpnl != 0 and rpnl != '':
                    conn.execute('''
                        UPDATE partial_close_events
                        SET resolved=1, realized_pnl=?, netOutcome=?, resolution_notes=?
                        WHERE id=?
                    ''', (
                        float(rpnl),
                        match.get('outcome', ''),
                        f"Cross-ref {datetime.now(timezone.utc).isoformat()}",
                        ev['id']
                    ))
                    resolved += 1

        _retry_write(_do)
        time.sleep(0.1)

    if resolved:
        log.info('Resolved %d events', resolved)
    return resolved

# ── Core poll ────────────────────────────────────────────────────────────────

def poll_wallets():
    wallets = get_open_wallets()
    log.info('Polling %d wallets...', len(wallets))
    total_pos = 0
    detected  = 0
    ts_now    = int(time.time())

    for i, wallet in enumerate(wallets, 1):
        try:
            positions = pm.get_user_positions(wallet)
        except Exception as e:
            log.debug('get_user_positions [%s]: %s', wallet[:16], e)
            time.sleep(0.05)
            continue

        if not positions:
            time.sleep(0.05)
            continue

        for raw in positions:
            size = raw.get('size', 0) or 0
            if size < MIN_POSITION_SIZE:
                continue

            market_id = str(raw.get('conditionId', '') or raw.get('market_id', ''))
            if not market_id:
                continue

            # Always save snapshot (upserts latest + inserts history)
            try:
                upsert_position(raw, ts_now)
            except Exception as e:
                log.debug('upsert error: %s', e)

            # Check for shrink vs prior snapshot
            prior_size = get_prior_size(wallet, market_id)
            if prior_size and prior_size > 0 and size < prior_size:
                shrink_pct = (prior_size - size) / prior_size * 100.0
                if shrink_pct >= MIN_SHRINK_PCT:
                    if is_duplicate_recent(wallet, market_id):
                        continue

                    log.warning(
                        'PARTIAL CLOSE: wallet=%s mkt=%s shrink=%.1f%% '
                        'size=%.0f->%.0f end=%s redeemable=%s',
                        wallet[:20], market_id[:16], shrink_pct,
                        prior_size, size, raw.get('endDate', ''),
                        raw.get('redeemable', False)
                    )
                    try:
                        insert_partial_close(raw, wallet, market_id, ts_now,
                                             prior_size, size, shrink_pct)
                    except Exception as e:
                        log.error("INSERT FAILED: %s", e)
                    detected += 1

            total_pos += 1

        if i % 50 == 0:
            log.info('  [%d/%d] positions=%d detected=%d', i, len(wallets), total_pos, detected)
        time.sleep(0.1)

    log.info('Poll complete — positions=%d partial_closes=%d', total_pos, detected)
    return detected

# ── Report ───────────────────────────────────────────────────────────────────

def print_report():
    c = _db(DB_PATH, row_factory=True)
    events = c.execute(
        'SELECT * FROM partial_close_events ORDER BY detected_at DESC LIMIT 100'
    ).fetchall()
    snap_count = c.execute('SELECT COUNT(*) FROM position_snapshots').fetchone()[0]
    latest_cnt = c.execute('SELECT COUNT(*) FROM position_latest').fetchone()[0]
    last_snap  = c.execute('SELECT MAX(ts_snapshot) FROM position_latest').fetchone()[0]
    c.close()

    print("\n" + "=" * 72)
    print("PARTIAL CLOSE EVENTS REPORT")
    print("=" * 72)

    if not events:
        print("\n  No partial close events detected.")
        print("  Run: python3 partial_close_detector.py        (continuous)")
        print("  Run: python3 partial_close_detector.py --once  (cron-friendly)")
    else:
        resolved = [e for e in events if e['resolved']]
        pending  = [e for e in events if not e['resolved']]
        print(f"\n  Total events: {len(events)}  |  Resolved: {len(resolved)}  |  Pending: {len(pending)}")

        print(f"\n  {'Wallet':<42} {'Market (truncated)':<22} {'Shrink%':>7} "
              f"{'Before':>10} {'After':>9} {'RealizedPnl':>12} {'Res':>4}  When")
        print("  " + "-" * 115)
        for e in events:
            wallet = e['wallet_address'][:38] + '..'
            mkt    = str(e['market_id'] or '')[:20]
            pnl    = f"${e['realized_pnl']:.0f}" if e['realized_pnl'] is not None else "pending"
            res    = "YES" if e['resolved'] else "wait"
            ts     = datetime.fromtimestamp(e['detected_at'], tz=timezone.utc).strftime('%m-%d %H:%M')
            print(f"  {wallet:<42} {mkt:<22} {e['shrink_pct']:>7.1f} "
                  f"{e['size_before']:>10,.0f} {e['size_after']:>9,.0f} "
                  f"{pnl:>12} {res:>5}  {ts}")
            if e['title']:
                print(f"    {e['title'][:68]}")

    print(f"\n  DB file   : {DB_PATH}")
    print(f"  Snapshots : {snap_count:,} history rows")
    print(f"  Latest    : {latest_cnt:,} active positions tracked")
    if last_snap:
        print(f"  Last poll : {datetime.fromtimestamp(last_snap, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print()

# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Partial close detector')
    parser.add_argument('--once',         action='store_true', help='Single poll then exit')
    parser.add_argument('--resolve',      action='store_true', help='Run resolution pass only')
    parser.add_argument('--report',       action='store_true', help='Print event report')
    parser.add_argument('--poll-interval', type=int, default=SNAPSHOT_INTERVAL,
                        help=f'Seconds between polls (default {SNAPSHOT_INTERVAL})')
    args = parser.parse_args()

    init_db()

    if args.report:
        print_report()
        return

    if args.resolve:
        n = resolve_partial_closes()
        print(f'Resolved {n} events.')
        return

    if args.once:
        poll_wallets()
        return

    log.info('Starting partial close detector (poll=%ds)...', args.poll_interval)
    cycle = 0
    while True:
        cycle += 1
        try:
            poll_wallets()
        except Exception as e:
            log.error('Cycle %d error: %s', cycle, e)
        if cycle % 20 == 0:
            resolve_partial_closes()
        time.sleep(args.poll_interval)

if __name__ == '__main__':
    main()