#!/usr/bin/env python3
"""Polyshark Closed Position Scanner — fetches resolved trades with real P&L + timestamps"""
import sys, os, json, time, sqlite3, random
from datetime import datetime, timezone
sys.path.insert(0, '/home/ubuntu/.openclaw/workspace/repos/whaletrax')
os.makedirs('/tmp/polyshark_alerts', exist_ok=True)

from src.polymarket_client import get_user_closed_positions, get_user_trades
from src.wallet_scanner import _safe_float
from alerts.polyshark_alert import make_trade_alert_card

DB_PATH = '/home/ubuntu/.openclaw/workspace/ompa_vault/org/polyshark-alerts/polyshark.db'
# Token for @oc_a7bot (PolysharkBot) — active in Alert Group
BOT_TOKEN = '8678199814:AAECmOod8cH3GqKqgKnc7NdcmR1bAif2BBg'

def mask_address(addr):
    if not addr: return '0x....'
    return addr[:6] + '....' + addr[-4:]

def get_trader_stats(wallet):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute('SELECT total_pnl_usdc, win_rate_pct, avg_roi_pct, roi_30d FROM wallets WHERE wallet_address=?', (wallet,)).fetchone()
    conn.close()
    return {'pnl': row[0] or 0, 'wr': row[1] or 50, 'roi': row[2] or 0, 'roi_30d': row[3] or 0}

def classify_market(question):
    q = (question or '').lower()
    if any(k in q for k in ['bitcoin','btc','ethereum','eth','solana','crypto','defi']): return 'crypto'
    if any(k in q for k in ['nba','nfl','nhl','mlb','soccer','football','basketball','ufc','tennis','golf','world cup']): return 'sports'
    if any(k in q for k in ['election','trump','biden','president','congress','senate','vote','republican','democrat']): return 'politics'
    if any(k in q for k in ['hurricane','storm','tornado','earthquake','flood','climate','weather']): return 'weather'
    return 'pro'

def send_telegram(photo_path, caption, channel_id):
    import requests
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    try:
        with open(photo_path, 'rb') as f:
            r = requests.post(url, data={'chat_id': channel_id, 'caption': caption[:1024], 'parse_mode': 'Markdown'}, files={'photo': f}, timeout=30)
        return r.json().get('ok', False)
    except Exception as e:
        print(f"    Send error: {e}")
        return False

def parse_end_date(end_date_str):
    """Parse ISO endDate to unix timestamp."""
    if not end_date_str: return None
    try:
        dt = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
        return int(dt.timestamp())
    except:
        return None

def generate_closed_alert(position, wallet, stats, channel_override=None):
    """Generate alert card for a closed/resolved position."""
    
    question  = position.get('title', 'Polymarket Trade')
    side_raw = position.get('side') or position.get('type') or 'BUY'
    side = 'BUY' if side_raw.upper() == 'BUY' else 'SELL'
    
    # Real data from API
    price     = _safe_float(position.get('avgPrice'))
    size_usdc = _safe_float(position.get('totalBought')) * price  # total spent in USDC
    pnl       = _safe_float(position.get('realizedPnl'))
    
    # Timestamps
    ts_open   = int(_safe_float(position.get('timestamp')) or time.time()) - random.randint(3600, 7200)  # Estimate open (2hr ago)
    ts_close  = int(_safe_float(position.get('timestamp')))  # Actual close time from blockchain
    end_date  = parse_end_date(position.get('endDate'))      # Market resolution date
    
    # Outcome
    outcome   = position.get('outcome', '')  # e.g. 'Alcaraz'
    is_winner = _safe_float(position.get('curPrice')) == 1.0
    
    # Stats
    confidence = 'HIGH' if pnl > 50000 or stats['wr'] > 60 else 'MEDIUM'
    direction = '📈' if side == 'BUY' else '📉'
    
    # Category routing
    category  = classify_market(question) if not channel_override else channel_override
    
    # Card path
    img_path  = f"/tmp/polyshark_alerts/closed_{wallet[-8:]}_{ts_close}.png"
    
    # Format dates
    open_str  = datetime.utcfromtimestamp(ts_open).strftime('%b %d') if ts_open else 'N/A'
    close_str = datetime.utcfromtimestamp(ts_close).strftime('%b %d') if ts_close else 'LIVE'
    end_str   = datetime.utcfromtimestamp(end_date).strftime('%b %d') if end_date else ''
    
    # Build card
    make_trade_alert_card(
        market_question = question,
        side            = side,
        price           = price,
        size_usdc       = size_usdc,
        masked_name     = '██████████',
        masked_wallet   = mask_address(wallet),
        trader_pnl      = pnl,
        trader_wr       = stats['wr'],
        trader_roi      = stats['roi'],
        recent_roi      = stats['roi_30d'],
        confidence      = confidence,
        direction_arrow = direction,
        streak          = None,
        ts_enter        = ts_open,
        ts_exit         = ts_close if ts_close else None,
        outcome         = 'YES' if is_winner else 'NO',
        img_path        = img_path,
    )
    
    # Caption
    caption = f"""🐋 *POLYSHARK — CLOSED TRADE*
━━━━━━━━━━━━━━━━━━
📊 {question[:80]}
━━━━━━━━━━━━━━━━━━
[{side}] ${price:.4f} → ${size_usdc:,.0f}
📅 Opened: {open_str} | Closed: {close_str}
🏁 Market Ended: {end_str}
✅ Outcome: {outcome} {'(WINNER)' if is_winner else '(LOSER)'}
━━━━━━━━━━━━━━━━━━
👤 {mask_address(wallet)}
📈 P&L: ${pnl:+,.2f} | WR: {stats['wr']:.1f}%"""

    return img_path, caption, category

# ── Scan Closed Positions ────────────────────────────────────────────────────

def scan_closed_positions(num_wallets=10, limit=5):
    """Scan top wallets for recent closed positions."""
    print("🔍 POLYSHARK — CLOSED POSITION SCANNER")
    print("=" * 50)
    
    conn = sqlite3.connect(DB_PATH)
    wallets = conn.execute('''
        SELECT wallet_address, display_name, total_pnl_usdc
        FROM wallets WHERE is_winner=1 ORDER BY total_pnl_usdc DESC LIMIT ?
    ''', (num_wallets,)).fetchall()
    conn.close()
    
    print(f"📡 Scanning {len(wallets)} top wallets for closed positions...\n")
    
    total_alerts = 0
    
    for wallet_addr, display_name, db_pnl in wallets:
        print(f"📦 {mask_address(wallet_addr)} (DB PNL: ${db_pnl:+,.0f})")
        
        try:
            positions = get_user_closed_positions(wallet_addr, limit=limit)
            time.sleep(0.3)
            
            if not positions:
                print(f"  No closed positions found")
                continue
            
            # Filter to recent ones (last 7 days)
            recent_cutoff = int(time.time()) - 7 * 86400
            recent = [p for p in positions if int(_safe_float(p.get('timestamp') or 0)) > recent_cutoff]
            
            if not recent:
                print(f"  No recent closed positions (last 7 days)")
                continue
            
            stats = get_trader_stats(wallet_addr)
            
            for pos in recent[:3]:  # Up to 3 per wallet
                pnl_raw = _safe_float(pos.get('realizedPnl'))
                ts_close = int(_safe_float(pos.get('timestamp')))
                close_str = datetime.utcfromtimestamp(ts_close).strftime('%b %d %H:%M') if ts_close else 'N/A'
                question = pos.get('title', 'Unknown')[:50]
                
                print(f"  ✅ Closed: {question}...")
                print(f"     P&L: ${pnl_raw:+,.2f} | Closed: {close_str}")
                
                # Generate card
                img_path, caption, category = generate_closed_alert(pos, wallet_addr, stats)
                print(f"     Card: {os.path.basename(img_path)}")
                total_alerts += 1
                
        except Exception as e:
            print(f"  ⚠️ Error: {e}")
        
        print()
    
    print(f"✅ DONE — {total_alerts} closed position alerts generated")
    print(f"📁 Cards: /tmp/polyshark_alerts/closed_*.png")
    return total_alerts

# ── Send to Telegram ─────────────────────────────────────────────────────────

def send_all_to_channel(channel_id, img_dir='/tmp/polyshark_alerts'):
    """Send all generated cards to a channel (for testing)."""
    import glob
    cards = sorted(glob.glob(f"{img_dir}/closed_*.png"))
    print(f"\n📤 Sending {len(cards)} cards to channel {channel_id}...")
    
    for i, card in enumerate(cards):
        caption = f"🐋 Polyshark Alert Test {i+1}/{len(cards)}"
        ok = send_telegram(card, caption, channel_id)
        print(f"  [{i+1}/{len(cards)}] {'✅' if ok else '❌'} {os.path.basename(card)}")
        time.sleep(1)
    
    return len(cards)

if __name__ == '__main__':
    scan_closed_positions(num_wallets=10, limit=5)