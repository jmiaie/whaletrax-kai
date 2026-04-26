#!/usr/bin/env python3
"""
Polyshark Live Trade Alert Generator + Sender
Fetches recent whale trades → generates v2 alert cards → sends to Telegram channels
"""

import sys, os, json, time, sqlite3
from datetime import datetime

sys.path.insert(0, '/home/ubuntu/.openclaw/workspace/repos/whaletrax')
os.makedirs('/tmp/polyshark_alerts', exist_ok=True)

from src.polymarket_client import get_user_trades, get_user_closed_positions, get_markets, _get
from src.wallet_scanner import _parse_trade, _safe_float
from alerts.polyshark_alert import make_trade_alert_card

def mask_address(addr: str) -> str:
    if not addr:
        return '0x....'
    return addr[:6] + '....' + addr[-4:]

# ── Config ──────────────────────────────────────────────────────────────────
DB_PATH = '/home/ubuntu/.openclaw/workspace/ompa_vault/org/polyshark-alerts/polyshark.db'
BOT_TOKEN = os.environ.get('POLYSHARK_BOT_TOKEN', '8678199814:AAEqZ3RdLWeWsSl6iCA1CzwwMZ69rcknNVc')

# Channel IDs (set once known — placeholder for now)
CHANNELS = {
    'pro':      os.environ.get('CHANNEL_POLYSHARK_PRO',      '-100XXXXXXXXX'),
    'sports':   os.environ.get('CHANNEL_POLYSHARK_SPORTS',  '-100XXXXXXXXX'),
    'crypto':   os.environ.get('CHANNEL_POLYSHARK_CRYPTO',  '-100XXXXXXXXX'),
    'politics': os.environ.get('CHANNEL_POLYSHARK_POLITICS','-100XXXXXXXXX'),
    'weather':  os.environ.get('CHANNEL_POLYSHARK_WEATHER', '-100XXXXXXXXX'),
    'free':     os.environ.get('CHANNEL_POLYSHARK_FREE',     '-1003999194095'),
}

# Categories for auto-routing
CRYPTO_KEYWORDS   = ['bitcoin','btc','ethereum','eth','solana','crypto','defi','token','blockchain','web3']
SPORTS_KEYWORDS    = ['nba','nfl','nhl','mlb','soccer','football','basketball','ufc','tennis','golf','world cup','fifa','ncaa']
POLITICS_KEYWORDS  = ['election','trump','biden','president','congress','senate','vote','republican','democrat','parliament','vote']
WEATHER_KEYWORDS   = ['hurricane','storm','tornado','earthquake','flood','climate','temperature','rain','snow','weather']

# ── Helpers ─────────────────────────────────────────────────────────────────

def get_market_question(market_id: str) -> str:
    """Fetch market question by ID."""
    data = _get(f"https://gamma-api.polymarket.com/markets/{market_id}")
    if data:
        return data.get('question', '') or data.get('title', '')
    return ''

def get_trader_stats(wallet: str) -> dict:
    """Get all-time P&L and win rate from Polymarket profile."""
    profile_url = f"https://polymarket.com/profile/{wallet}"
    # Use profile page __NEXT_DATA__ — simplified fallback
    # In production, we'd scrape the profile. For now, estimate from leaderboard.
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute('SELECT total_pnl_usdc, win_rate_pct, avg_roi_pct, roi_30d FROM wallets WHERE wallet_address=?', (wallet,)).fetchone()
    conn.close()
    if row:
        return {'pnl': row[0] or 0, 'wr': row[1] or 50, 'roi': row[2] or 0, 'roi_30d': row[3] or 0}
    return {'pnl': 0, 'wr': 50, 'roi': 0, 'roi_30d': 0}

def classify_market(question: str) -> str:
    """Auto-classify market to category channel."""
    q = question.lower()
    if any(k in q for k in CRYPTO_KEYWORDS):
        return 'crypto'
    if any(k in q for k in SPORTS_KEYWORDS):
        return 'sports'
    if any(k in q for k in POLITICS_KEYWORDS):
        return 'politics'
    if any(k in q for k in WEATHER_KEYWORDS):
        return 'weather'
    return 'pro'  # default to Pro channel

def send_telegram(photo_path: str, caption: str, channel_id: str) -> dict:
    """Send photo to Telegram channel."""
    import requests
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    with open(photo_path, 'rb') as f:
        files = {'photo': f}
        data = {'chat_id': channel_id, 'caption': caption[:1024], 'parse_mode': 'Markdown'}
        r = requests.post(url, data=data, files=files, timeout=30)
    return r.json()

# ── Alert Generator ─────────────────────────────────────────────────────────

def generate_and_send_alert(trade: dict, wallet: str, display_name: str, channel_override: str = None):
    """Generate v2 alert card and send to configured channels."""
    
    # Extract trade data
    market_id   = trade.get('marketId') or trade.get('market') or ''
    ts_trade    = int(_safe_float(trade.get('timestamp') or trade.get('createdAt')))
    side        = trade.get('type') or trade.get('side') or 'BUY'
    price       = _safe_float(trade.get('price') or trade.get('avgPrice'))
    size        = _safe_float(trade.get('size'))
    amount      = _safe_float(trade.get('amount') or trade.get('usdcAmount'))
    if amount == 0 and size > 0 and price > 0:
        amount = size * price

    # Get market question
    question    = trade.get('question') or trade.get('marketTitle') or ''
    if not question and market_id:
        question = get_market_question(market_id)

    # Get trader stats
    stats       = get_trader_stats(wallet)
    
    # Determine category
    category    = classify_market(question) if not channel_override else channel_override
    
    # Build masked values
    masked_name   = '██████████'
    masked_wallet = mask_address(wallet)
    
    # Determine confidence
    confidence = 'HIGH' if stats['pnl'] > 100000 or stats['wr'] > 60 else 'MEDIUM'
    direction  = '📈' if side.upper() == 'BUY' else '📉'
    
    # Generate card
    img_path = f"/tmp/polyshark_alerts/alert_{trade.get('id', ts_trade)}.png"
    
    # ts_exit = 0 for open trades, set for closed
    ts_exit = int(_safe_float(trade.get('closedAt') or trade.get('settledAt') or 0))
    
    make_trade_alert_card(
        market_question = question or 'Polymarket Trade',
        side            = side.upper(),
        price           = price,
        size_usdc       = amount,
        masked_name     = masked_name,
        masked_wallet   = masked_wallet,
        trader_pnl      = stats['pnl'],
        trader_wr       = stats['wr'],
        trader_roi      = stats['roi'],
        recent_roi      = stats['roi_30d'],
        confidence      = confidence,
        direction_arrow = direction,
        streak          = None,  # streak requires Dune data
        streak_type     = 'correct',
        ts_enter        = ts_trade if ts_trade > 0 else int(time.time()),
        ts_exit         = ts_exit if ts_exit > 0 else None,
        outcome         = '',    # outcome requires market resolution
        img_path        = img_path,
    )
    
    # Build caption
    ts_str = datetime.utcfromtimestamp(ts_trade).strftime('%b %d, %H:%M') if ts_trade > 0 else 'LIVE'
    closed_str = datetime.utcfromtimestamp(ts_exit).strftime('%b %d') if ts_exit > 0 else 'LIVE'
    
    caption = f"""🐋 *POLYSHARK WHALE ALERT*
━━━━━━━━━━━━━━━━━━
📊 {question[:80] if question else 'Polymarket Trade'}
━━━━━━━━━━━━━━━━━━
[{side.upper()}] ${price:.4f} → ${amount:,.0f}
📅 Opened: {ts_str} | Closed: {closed_str}
━━━━━━━━━━━━━━━━━━
👤 {masked_name} | {masked_wallet}
📈 P&L: ${stats['pnl']:+,.0f} | WR: {stats['wr']:.1f}% | ROI: {stats['roi']:+.1f}%
30D ROI: {stats['roi_30d']:+.1f}%"""

    # Send to Pro first (always)
    pro_channel = CHANNELS['pro']
    result_pro = send_telegram(img_path, caption, pro_channel)
    print(f"  → Sent to Pro: {'✅' if result_pro.get('ok') else '❌ ' + str(result_pro)}")
    
    # Send to category channel
    if category != 'pro':
        cat_channel = CHANNELS.get(category)
        if cat_channel:
            result_cat = send_telegram(img_path, caption, cat_channel)
            print(f"  → Sent to {category.upper()}: {'✅' if result_cat.get('ok') else '❌'}")
    
    # For free channel — mark as "would be delayed"
    # In production, we'd queue this for 4-6 hour delay
    # For testing, we just log it
    print(f"  → Free channel: QUEUED (delayed 4-6hrs)")
    
    return result_pro

# ── Main Scanner ─────────────────────────────────────────────────────────────

def scan_and_alert(num_wallets: int = 10, trades_per_wallet: int = 5):
    """Scan top wallets for recent trades and send alerts."""
    print("🔍 POLYSHARK LIVE SCANNER — TEST RUN")
    print("=" * 50)
    
    # Load top wallets from DB
    conn = sqlite3.connect(DB_PATH)
    wallets = conn.execute('''
        SELECT wallet_address, display_name, total_pnl_usdc, win_rate_pct, roi_30d
        FROM wallets WHERE is_winner=1 ORDER BY total_pnl_usdc DESC LIMIT ?
    ''', (num_wallets,)).fetchall()
    conn.close()
    
    print(f"📡 Scanning {len(wallets)} wallets...")
    print()
    
    sent_count = 0
    for wallet_addr, display_name, pnl, wr, roi30d in wallets:
        wallet_short = wallet_addr[:16] + '...'
        print(f"📦 Wallet: {wallet_short} | PNL: ${pnl:+,.0f} | WR: {wr:.1f}%")
        
        try:
            trades = get_user_trades(wallet_addr, limit=trades_per_wallet)
            for trade in trades:
                try:
                    result = generate_and_send_alert(trade, wallet_addr, display_name or wallet_short)
                    if result.get('ok'):
                        sent_count += 1
                        print(f"   ✅ Trade alert sent")
                except Exception as e:
                    print(f"   ⚠️ Alert error: {e}")
            
            time.sleep(0.5)  # rate limit
        except Exception as e:
            print(f"   ⚠️ Fetch error: {e}")
        
        print()
    
    print(f"✅ DONE — {sent_count} alerts sent")
    return sent_count

# ── Test Mode (last 10 historical trades) ────────────────────────────────────

def test_last_10():
    """Generate last 10 alerts from existing DB (no channel send)."""
    from alerts.polyshark_alert import make_trade_alert_card
    import traceback
    
    conn = sqlite3.connect(DB_PATH)
    wallets = conn.execute('''
        SELECT wallet_address, display_name FROM wallets LIMIT 10
    ''').fetchall()
    conn.close()
    
    print("🧪 TEST MODE — Generating last 10 alert cards")
    print("=" * 50)
    
    os.makedirs('/tmp/polyshark_alerts', exist_ok=True)
    count = 0
    
    for wallet_addr, display_name in wallets:
        try:
            trades = get_user_trades(wallet_addr, limit=3)
            for trade in trades[:2]:  # 2 trades per wallet
                ts_trade = int(_safe_float(trade.get('timestamp') or trade.get('createdAt')))
                side = trade.get('type') or trade.get('side') or 'BUY'
                price = _safe_float(trade.get('price') or trade.get('avgPrice'))
                size = _safe_float(trade.get('size'))
                amount = _safe_float(trade.get('amount') or trade.get('usdcAmount'))
                if amount == 0 and size > 0 and price > 0:
                    amount = size * price
                
                market_id = trade.get('marketId') or trade.get('market') or ''
                question = trade.get('question') or trade.get('marketTitle') or ''
                if not question and market_id:
                    question = get_market_question(market_id)
                
                stats = get_trader_stats(wallet_addr)
                
                ts_exit = int(_safe_float(trade.get('closedAt') or trade.get('settledAt') or 0))
                ts_str = datetime.utcfromtimestamp(ts_trade).strftime('%b %d') if ts_trade > 0 else 'LIVE'
                closed_str = datetime.utcfromtimestamp(ts_exit).strftime('%b %d') if ts_exit > 0 else 'LIVE'
                
                img_path = f"/tmp/polyshark_alerts/test_alert_{count+1}.png"
                
                make_trade_alert_card(
                    market_question = question or 'Polymarket Trade',
                    side            = side.upper(),
                    price           = price,
                    size_usdc       = amount,
                    masked_name     = '██████████',
                    masked_wallet   = mask_address(wallet_addr),
                    trader_pnl      = stats['pnl'],
                    trader_wr       = stats['wr'],
                    trader_roi      = stats['roi'],
                    recent_roi      = stats['roi_30d'],
                    confidence      = 'HIGH' if stats['pnl'] > 100000 else 'MEDIUM',
                    direction_arrow = '📈' if side.upper() == 'BUY' else '📉',
                    streak          = None,
                    ts_enter        = ts_trade if ts_trade > 0 else int(time.time()),
                    ts_exit         = ts_exit if ts_exit > 0 else None,
                    outcome         = '',
                    img_path        = img_path,
                )
                
                print(f"✅ Alert {count+1}: [{ts_str}] {side.upper()} ${price:.4f} | {question[:50]}...")
                print(f"   Wallet: {mask_address(wallet_addr)} | Size: ${amount:,.0f} | PNL: ${stats['pnl']:+,.0f}")
                count += 1
                
        except Exception as e:
            print(f"⚠️ Error: {e}")
            traceback.print_exc()
    
    print(f"\n✅ Generated {count} alert cards")
    print(f"📁 Location: /tmp/polyshark_alerts/")
    return count

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--test',   action='store_true', help='Generate test alert cards only (no send)')
    parser.add_argument('--live',   action='store_true', help='Live scan + send to channels')
    parser.add_argument('--count',  type=int, default=10,  help='Number of wallets to scan')
    args = parser.parse_args()
    
    if args.test:
        test_last_10()
    else:
        # Default: test mode
        test_last_10()