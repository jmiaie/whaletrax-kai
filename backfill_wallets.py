#!/usr/bin/env python3
"""
Wallet Backfill Script — Tai's version
Pulls full on-chain history for top N whale wallets from Polymarket API.
Stores in wallet_tracker.db with trades + positions tables.
Handles pagination to get complete history.
"""
import sys, os, json, logging, time, sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('/home/ubuntu/whaletrax-public')
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('backfill')

import requests
from src import polymarket_client as pm
from src.wallet_scanner import _safe_float

DB_PATH = ROOT / 'wallet_tracker.db'

# ── DB Setup ─────────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute('''
        CREATE TABLE IF NOT EXISTS tracked_wallets (
            wallet_address TEXT PRIMARY KEY,
            display_name TEXT,
            total_pnl REAL DEFAULT 0,
            win_rate_pct REAL DEFAULT 0,
            roi_pct REAL DEFAULT 0,
            roi_30d REAL DEFAULT 0,
            total_positions INTEGER DEFAULT 0,
            total_trades INTEGER DEFAULT 0,
            updated_at TEXT
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS wallet_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet_address TEXT NOT NULL,
            trade_id TEXT,
            market_id TEXT,
            market_question TEXT,
            side TEXT,
            outcome TEXT,
            price REAL,
            size REAL,
            cost_usdc REAL,
            pnl REAL,
            timestamp INTEGER,
            end_date TEXT,
            UNIQUE(wallet_address, trade_id)
        )
    ''')
    conn.execute('''
        CREATE INDEX IF NOT EXISTS idx_wallet_trades_wallet ON wallet_trades(wallet_address)
    ''')
    conn.execute('''
        CREATE INDEX IF NOT EXISTS idx_wallet_trades_market ON wallet_trades(market_id)
    ''')
    conn.commit()
    return conn

def wallet_exists(conn, wallet):
    row = conn.execute('SELECT 1 FROM tracked_wallets WHERE wallet_address=?', (wallet,)).fetchone()
    return row is not None

def upsert_wallet(conn, wallet, name=''):
    now = datetime.now(timezone.utc).isoformat()
    conn.execute('''
        INSERT INTO tracked_wallets (wallet_address, display_name, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(wallet_address) DO UPDATE SET
            display_name = COALESCE(excluded.display_name, display_name),
            updated_at = ?
    ''', (wallet, name, now, now))

def insert_trade(conn, wallet, trade):
    """Insert a trade, ignore duplicates."""
    trade_id = str(trade.get('id') or trade.get('tradeId') or trade.get('transactionHash') or '')
    market_id = str(trade.get('conditionId') or trade.get('market') or trade.get('marketId') or '')
    question = trade.get('title') or trade.get('question') or ''
    side = str(trade.get('side') or '')
    outcome = str(trade.get('outcome') or '')
    price = _safe_float(trade.get('price') or trade.get('avgPrice') or 0)
    size = _safe_float(trade.get('size') or 0)
    cost = _safe_float(trade.get('cost') or trade.get('costBasis') or (size * price if size and price else 0))
    pnl = _safe_float(trade.get('realizedPnl') or trade.get('pnl') or 0)
    ts = int(_safe_float(trade.get('timestamp') or 0))
    end_date = str(trade.get('endDate') or '')
    
    try:
        conn.execute('''
            INSERT OR IGNORE INTO wallet_trades 
            (wallet_address, trade_id, market_id, market_question, side, outcome, price, size, cost_usdc, pnl, timestamp, end_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (wallet, trade_id, market_id, question, side, outcome, price, size, cost, pnl, ts, end_date))
    except Exception as e:
        pass  # Skip duplicates

def compute_stats(conn, wallet):
    """Compute win rate, total P&L from trades table."""
    rows = conn.execute('''
        SELECT pnl, market_id, end_date FROM wallet_trades 
        WHERE wallet_address=? AND pnl IS NOT NULL
    ''', (wallet,)).fetchall()
    
    if not rows:
        return
    
    total_pnl = sum(r[0] or 0 for r in rows)
    total_cost = sum(r[1] or 0 for r in rows if r[1])  # placeholder
    
    # Win = positive PnL, Loss = negative
    wins = sum(1 for r in rows if (r[0] or 0) > 0)
    total = len(rows)
    wr = (wins / total * 100) if total > 0 else 0
    
    # Also check closed positions for realized P&L
    conn.execute('''
        UPDATE tracked_wallets SET 
            total_pnl = COALESCE((SELECT SUM(realizedPnl) FROM (
                SELECT realizedPnl FROM wallet_trades WHERE wallet_address=? AND realizedPnl IS NOT NULL
            )), 0),
            total_trades = ?,
            win_rate_pct = ?
        WHERE wallet_address=?
    ''', (wallet, total, wr, wallet))
    conn.commit()

# ── Backfill one wallet ────────────────────────────────────────────────────────
def backfill_wallet(conn, wallet, name=''):
    log.info(f'Backfilling {wallet[:12]}... ({name or "unknown"})')
    
    # Ensure wallet in DB
    upsert_wallet(conn, wallet, name)
    
    # Track counts
    trade_count = 0
    page = 1
    
    # Paginate through trades
    offset = 0
    limit = 50
    max_pages = 200
    
    while page <= max_pages:
        url = f"{pm.config.DATA_API_BASE}/trades"
        params = {'user': wallet, 'limit': limit, 'offset': offset}
        
        try:
            data = pm._get(url, params)
            if not data or not isinstance(data, list):
                break
            
            items = data if isinstance(data, list) else data.get('data', [])
            if not items:
                break
            
            for item in items:
                insert_trade(conn, wallet, item)
                trade_count += 1
            
            if len(items) < limit:
                break  # Last page
            
            offset += limit
            page += 1
            
            if trade_count % 500 == 0:
                conn.commit()
                log.info(f'  {wallet[:12]}... {trade_count} trades so far')
            
            if trade_count >= 10000:
                log.info(f'  Hit 10K cap, stopping pagination for {wallet[:12]}...')
                break
                
        except Exception as e:
            log.warning(f'  Error at page {page} for {wallet[:12]}...: {e}')
            break
    
    conn.commit()
    
    # Compute stats
    compute_stats(conn, wallet)
    
    log.info(f'  ✓ {wallet[:12]}... — {trade_count} trades stored')
    return trade_count

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    log.info('=== Wallet Backfill — pulling full on-chain history ===')
    
    conn = init_db()
    
    # Get top 20 from leaderboard
    log.info('Fetching top 20 wallets from Polymarket leaderboard...')
    raw = pm.get_leaderboard(limit=20)
    if not raw:
        log.error('Could not fetch leaderboard — check API connection')
        return
    
    wallets = []
    for entry in raw:
        addr = (entry.get('proxyWallet') or entry.get('address') or '').strip()
        name = entry.get('userName', '') or ''
        if addr.startswith('0x') and len(addr) == 42:
            wallets.append((addr, name))
    
    log.info(f'Got {len(wallets)} wallets from leaderboard')
    
    total_trades = 0
    for i, (wallet, name) in enumerate(wallets):
        log.info(f'[{i+1}/{len(wallets)}] Processing {wallet[:12]}... ({name})')
        
        # Check if already fully backfilled
        existing = conn.execute('SELECT total_trades FROM tracked_wallets WHERE wallet_address=?', (wallet,)).fetchone()
        if existing and existing[0] >= 5000:
            log.info(f'  Already has {existing[0]} trades — skipping')
            total_trades += existing[0]
            continue
        
        count = backfill_wallet(conn, wallet, name)
        total_trades += count
        
        # Rate limit between wallets
        time.sleep(1)
    
    log.info(f'=== Backfill complete: {total_trades} total trades across {len(wallets)} wallets ===')
    
    # Summary
    conn.commit()
    summary = conn.execute('SELECT wallet_address, total_trades, total_pnl, win_rate_pct FROM tracked_wallets ORDER BY total_trades DESC LIMIT 10').fetchall()
    log.info('Top wallets by trade count:')
    for r in summary:
        log.info(f'  {r[0][:12]}... | {r[1]} trades | PnL: ${r[2]:,.0f} | WR: {r[3]:.1f}%')
    
    conn.close()

if __name__ == '__main__':
    main()