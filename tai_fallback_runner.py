#!/usr/bin/env python3
"""
WhaleTrax Fallback Runner — Tai's version
Uses Polymarket public API + OpenClaw message tool to send whale alerts.
No bot token needed — runs as a cron job via OpenClaw's agent system.
"""
import sys, os, json, logging, time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── Setup ──────────────────────────────────────────────────────────────────────
ROOT = Path('/home/ubuntu/whaletrax-public')
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('tai_fallback')

import requests
from src import polymarket_client as pm
from src.wallet_scanner import _safe_float, _parse_trade


# ── Channels (from OpenClaw config / team vault) ───────────────────────────────
CHANNELS = {
    'alert':  '-1003786930778',   # Alert Hub
    'sports': '-1003948034686',   # Sports
    'free':   '-1003999194095',   # Free
    'top':    '-1003957370508',   # TOP PLAYS
}

# ── Filters ────────────────────────────────────────────────────────────────────
MIN_PROFIT_USDC = 500
MIN_ROI_PCT = 50
MIN_SIZE_USDC = 100
MAX_TRADES_PER_RUN = 5

# ── High-priority whale list ───────────────────────────────────────────────────
def load_high_priority_whales():
    """Load high-priority whale addresses from team vault."""
    vault = Path('/home/ubuntu/team-vault/teams/whaletrax/high_priority_whales.json')
    if not vault.exists():
        log.warning(f'High-priority whales file not found: {vault}')
        return []
    
    # Parse markdown-style JSON
    text = vault.read_text()
    # Extract addresses from the markdown format
    addresses = []
    for line in text.split('\n'):
        if line.strip().startswith('0x') and len(line.strip()) >= 40:
            addr = line.strip().split()[0]
            addresses.append(addr)
    
    log.info(f'Loaded {len(addresses)} high-priority whale addresses')
    return addresses

def get_top_wallets_from_leaderboard(n=20):
    """Get top wallets from Polymarket public leaderboard."""
    raw = pm.get_leaderboard(limit=n)
    if not raw:
        return []
    wallets = []
    for entry in raw:
        # Use proxyWallet (from leaderboard API), fallback to address
        addr = (entry.get('proxyWallet') or entry.get('address') or '').strip()
        if addr.startswith('0x') and len(addr) == 42:
            wallets.append(addr)
    return wallets

def get_recent_closed_positions(wallet: str, hours=24, limit=10):
    """Get recent closed positions for a wallet from Polymarket API."""
    try:
        data = pm.get_user_closed_positions(wallet, limit=limit)
        if not data:
            return []
        
        positions = []
        for item in data:
            # Parse PnL — use realizedPnl (or profit/realizedPnl)
            pnl = _safe_float(item.get('realizedPnl') or item.get('profit') or item.get('pnl') or 0)
            
            # Parse cost basis: totalBought * avgPrice
            total_bought = _safe_float(item.get('totalBought') or 0)
            avg_price = _safe_float(item.get('avgPrice') or 0)
            cost = total_bought * avg_price if total_bought and avg_price else 0
            
            if not cost:
                cost = _safe_float(item.get('cost') or item.get('costBasis') or 0)
            
            roi = (pnl / cost * 100) if cost > 0 else 0
            size_usdc = cost
            
            # Filter
            if pnl < MIN_PROFIT_USDC:
                continue
            if abs(roi) < MIN_ROI_PCT:
                continue
            if size_usdc < MIN_SIZE_USDC:
                continue
            
            # Parse timestamp
            ts = int(_safe_float(item.get('timestamp') or item.get('createdAt') or 0))
            if ts > 0:
                age_hours = (datetime.now(timezone.utc).timestamp() - ts) / 3600
                if age_hours > hours:
                    continue
            
            # Use title (or question) as question
            question = item.get('title') or item.get('question') or item.get('marketTitle') or 'Unknown'
            outcome = str(item.get('outcome') or item.get('outcomeIndex') or '?')
            # Use conditionId as market_id
            market_id = str(item.get('conditionId') or item.get('market') or item.get('marketId') or '')
            
            positions.append({
                'wallet': wallet,
                'question': question,
                'outcome': outcome,
                'market_id': market_id,
                'pnl': pnl,
                'roi': roi,
                'size_usdc': size_usdc,
                'timestamp': ts,
                'avg_price': avg_price,
            })
        return positions
    except Exception as e:
        log.warning(f'Error fetching positions for {wallet[:10]}...: {e}')
        return []

def classify(question: str) -> str:
    """Classify market to channel."""
    q = question.lower()
    sports_kw = ['nba','nfl','nhl','mlb','soccer','football','basketball','ufc','tennis','golf','world cup','fifa','ncaa','knicks','spurs','lakers','celtics','yankees','dodgers']
    crypto_kw = ['bitcoin','btc','ethereum','eth','solana','crypto','defi','token']
    politics_kw = ['election','trump','biden','president','congress','senate','republican','democrat']
    world_kw = ['iran','israel','ukraine','russia','china','taiwan','gaza','war','military']
    
    if any(k in q for k in sports_kw):
        return 'sports'
    if any(k in q for k in crypto_kw):
        return 'crypto'
    if any(k in q for k in politics_kw):
        return 'politics'
    if any(k in q for k in world_kw):
        return 'world'
    return 'free'

def format_alert_card(position: dict, market_id: str) -> str:
    """Format a simple text card for a position."""
    side_map = {'YES': 'UP', 'NO': 'DOWN', '1': 'UP', '0': 'DOWN'}
    outcome = position.get('outcome', '?')
    side = side_map.get(str(outcome).upper(), 'UP')
    
    direction = '⬆️' if side == 'UP' else '⬇️'
    profit = position['pnl']
    roi = position['roi']
    size = position['size_usdc']
    question = position['question']
    wallet = position['wallet']
    ts = position.get('timestamp', 0)
    
    # Format timestamp
    if ts > 0:
        trade_date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d')
        open_short = trade_date[5:10]
    else:
        open_short = '??'
    
    abbrev = f'{wallet[:8]}...{wallet[-6:]}'
    
    card = f"""🟢 🦈 [Polyshark PRO] 🦈🟢
📅 O: {open_short} | C: ???
————————————————————————
🎟️ {question}
🔗 https://polymarket.com/event/{market_id}
————————————————————————
💰 +${profit:,.0f} (+{roi:.1f}% potential ROI)
💵 ${size:,.0f} position
{direction} BET {side}
————————————————————————
🌊 [{abbrev}](https://polymarket.com/profile/{wallet}) 🐋"""
    
    return card

def send_telegram(text: str, channel_id: str) -> bool:
    """Send message via OpenClaw message tool ( stubs to HTTP call for now)."""
    # For now, print to log — actual send happens via the OpenClaw message tool
    # when this runs as an agent Turn
    log.info(f'[WOULD SEND to {channel_id}]: {text[:100]}...')
    return True

def main():
    log.info('=== Tai Fallback Runner starting ===')
    
    # Load whale list
    whales = load_high_priority_whales()
    if not whales:
        log.warning('No high-priority whales found, using leaderboard')
        whales = get_top_wallets_from_leaderboard(20)
    
    if not whales:
        log.error('No whales to scan')
        return
    
    # Deduplicate
    whales = list(dict.fromkeys(whales))[:20]
    
    qualifying_positions = []
    
    for wallet in whales:
        log.info(f'Scanning {wallet[:10]}...')
        positions = get_recent_closed_positions(wallet, hours=48, limit=5)
        for pos in positions:
            # Check market_id
            if not pos.get('market_id'):
                continue
            qualifying_positions.append(pos)
        
        if len(qualifying_positions) >= MAX_TRADES_PER_RUN:
            break
    
    log.info(f'Found {len(qualifying_positions)} qualifying positions')
    
    for pos in qualifying_positions[:MAX_TRADES_PER_RUN]:
        card = format_alert_card(pos, pos['market_id'])
        category = classify(pos['question'])
        
        log.info(f'Sending to {category}: {pos["question"][:50]}...')
        log.info(f'Card:\n{card}')
    
    log.info('=== Tai Fallback Runner done ===')

if __name__ == '__main__':
    main()