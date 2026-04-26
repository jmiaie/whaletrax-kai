#!/usr/bin/env python3
"""Standalone test: generate last 10 alert cards"""
import sys, os, json, time, sqlite3
from datetime import datetime

sys.path.insert(0, '/home/ubuntu/.openclaw/workspace/repos/whaletrax')
os.makedirs('/tmp/polyshark_alerts', exist_ok=True)

from src.polymarket_client import get_user_trades, _get
from src.wallet_scanner import _safe_float
from alerts.polyshark_alert import make_trade_alert_card

DB_PATH = '/home/ubuntu/.openclaw/workspace/ompa_vault/org/polyshark-alerts/polyshark.db'

def mask_address(addr):
    if not addr:
        return '0x....'
    return addr[:6] + '....' + addr[-4:]

def get_market_question(market_id):
    if not market_id:
        return ''
    data = _get(f"https://gamma-api.polymarket.com/markets/{market_id}")
    if data:
        return data.get('question', '') or data.get('title', '')
    return ''

def get_trader_stats(wallet):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute('SELECT total_pnl_usdc, win_rate_pct, avg_roi_pct, roi_30d FROM wallets WHERE wallet_address=?', (wallet,)).fetchone()
    conn.close()
    if row:
        return {'pnl': row[0] or 0, 'wr': row[1] or 50, 'roi': row[2] or 0, 'roi_30d': row[3] or 0}
    return {'pnl': 0, 'wr': 50, 'roi': 0, 'roi_30d': 0}

print("🧪 POLYSHARK TEST — Generating last 10 alert cards")
print("=" * 50)

conn = sqlite3.connect(DB_PATH)
wallets = conn.execute('SELECT wallet_address, display_name FROM wallets LIMIT 10').fetchall()
conn.close()

count = 0
for wallet_addr, display_name in wallets:
    try:
        trades = get_user_trades(wallet_addr, limit=3)
        for trade in trades[:2]:
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
                market_question=question or 'Polymarket Trade',
                side=side.upper(),
                price=price,
                size_usdc=amount,
                masked_name='██████████',
                masked_wallet=mask_address(wallet_addr),
                trader_pnl=stats['pnl'],
                trader_wr=stats['wr'],
                trader_roi=stats['roi'],
                recent_roi=stats['roi_30d'],
                confidence='HIGH' if stats['pnl'] > 100000 else 'MEDIUM',
                direction_arrow='📈' if side.upper() == 'BUY' else '📉',
                streak=None,
                ts_enter=ts_trade if ts_trade > 0 else int(time.time()),
                ts_exit=ts_exit if ts_exit > 0 else None,
                outcome='',
                img_path=img_path,
            )

            print(f"✅ Alert {count+1}: [{ts_str}] {side.upper()} ${price:.4f} | {question[:55]}...")
            print(f"   {mask_address(wallet_addr)} | Size: ${amount:,.0f} | PNL: ${stats['pnl']:+,.0f} | WR: {stats['wr']:.1f}%")
            count += 1

            time.sleep(0.2)
    except Exception as e:
        print(f"⚠️ Error: {e}")

print(f"\n✅ Generated {count} alert cards → /tmp/polyshark_alerts/")