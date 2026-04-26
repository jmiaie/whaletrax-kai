#!/usr/bin/env python3
"""
Polyshark Entry Tracker v5 — Final
Jeff Milam spec (2026-04-25):

FILTER (at Swarm2bot level — before Kai):
  1. entry price == $0.0000  → REJECT (don't send)
  2. Stock tickers ($AMAZON, $YELLEN) → REJECT
  3. Resolved markets (redeemable=true) → REJECT
  4. endDate < Jan 1, 2025 → REJECT
  5. Market ending in < 48h → REJECT (stale entry, no value)
  6. currentValue < $50 AND cashPnl near 0 → REJECT (tiny/meaningless)
  7. Already alerted (market_id+wallet dedup) → SKIP

ALL positions logged to DB regardless of alert eligibility.

CARD FORMAT (exact):
  🐋 WHALE ENTRY ALERT
  ━━━━━━━━━━━━━━━━━━
  📊 [market question]
  ━━━━━━━━━━━━━━━━━━
  📌 [SIDE] [outcome] @ $[entry] → $[USDC stake]
  📅 Detected: [date]
  📁 Category: [category]
  💰 Unrealized P&L: $[amount]
  ━━━━━━━━━━━━━━━━━━
  👤 [masked wallet]
  🔗 [real Polymarket URL]
  ━━━━━━━━━━━━━━━━━━
  Polyshark · Real-time whale tracking

Kai's role: filter → category route → delay → forward. NOT card generation.
"""

import sys, os, json, time, sqlite3, traceback
from datetime import datetime, timezone, timedelta

sys.path.insert(0, '/home/ubuntu/.openclaw/workspace/repos/whaletrax')
os.makedirs('/tmp/polyshark_alerts', exist_ok=True)

from src.polymarket_client import get_user_positions
from src.wallet_scanner import _safe_float
from alerts.polyshark_alert import make_trade_alert_card

BOT_TOKEN      = '8741871021:AAGtWosFayhX82ls7W3ZNcNh5cIQcEbAEpM'
ALERT_GROUP_ID = '-1003786930778'
DB_PATH        = '/home/ubuntu/.openclaw/workspace/repos/whaletrax/wallet_tracker.db'
MIN_HOURS      = 48
POLL_WALLETS   = 20
SEND_GAP       = 3  # seconds between Telegram sends

# ── Helpers ──────────────────────────────────────────────────────────────────

def mask_address(addr):
    if not addr: return '0x....'
    return addr[:6] + '....' + addr[-4:]

def send_telegram(photo_path, caption, channel_id=ALERT_GROUP_ID):
    import requests
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    for attempt in range(3):
        try:
            with open(photo_path, 'rb') as f:
                r = requests.post(url,
                    data={'chat_id': channel_id, 'caption': caption[:1024], 'parse_mode': 'Markdown'},
                    files={'photo': f}, timeout=30)
            resp = r.json()
            if resp.get('ok'): return resp
            if 'Too Many Requests' in str(resp):
                wait = int(resp.get('parameters', {}).get('retry_after', 30))
                print(f"    ⏳ Rate limit — sleeping {wait+5}s...")
                time.sleep(wait + 5)
                continue
            return resp
        except Exception as e:
            print(f"    ❌ Send error: {e}")
            if attempt == 2: return {'ok': False}
            time.sleep(5)
    return {'ok': False}

def load_wallets():
    with open('/home/ubuntu/.openclaw/workspace/repos/whaletrax/wallets_seed.json') as f:
        data = json.load(f)
    return data if isinstance(data, list) else data.get('wallets', [])

def get_stats(wallet_addr):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute('''
        SELECT total_pnl, win_rate_pct, roi_pct, roi_30d
        FROM tracked_wallets WHERE wallet_address=?
    ''', (wallet_addr,)).fetchone()
    conn.close()
    return {'pnl': row[0] or 0, 'wr': row[1] or 50,
            'roi': row[2] or 0, 'roi30d': row[3] or 0} if row else {'pnl':0,'wr':50,'roi':0,'roi30d':0}

def is_new_position(conn, wallet_addr, market_id):
    return not conn.execute('''
        SELECT 1 FROM wallet_trades WHERE wallet_address=? AND market_id=? AND alert_sent=1
    ''', (wallet_addr, market_id)).fetchone()

def log_trade(conn, **kw):
    conn.execute('''
        INSERT OR IGNORE INTO wallet_trades
        (wallet_address, trade_id, market_id, market_question, side, entry_price,
         size_usdc, ts_enter, is_closed, alert_sent, ts_created)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, unixepoch())
    ''', (kw['wallet'], kw.get('trade_id',''), kw['market_id'],
         kw.get('question',''), kw['side'], kw.get('price', 0),
         kw.get('size_usdc', 0), kw.get('ts_enter', int(time.time()))))
    conn.commit()

def mark_sent(conn, wallet_addr, market_id):
    conn.execute('''
        UPDATE wallet_trades SET alert_sent=1, alert_sent_at=unixepoch()
        WHERE wallet_address=? AND market_id=? AND alert_sent=0
    ''', (wallet_addr, market_id))
    conn.commit()

def classify(question):
    q = (question or '').lower()
    if any(k in q for k in ['bitcoin','btc','eth','crypto','solana','defi']): return 'crypto'
    if any(k in q for k in ['nba','nfl','nhl','mlb','soccer','ufc','tennis','world cup','fifa']): return 'sports'
    if any(k in q for k in ['election','trump','biden','congress','senate','vote','republican']): return 'politics'
    if any(k in q for k in ['hurricane','storm','tornado','flood','climate','weather']): return 'weather'
    if any(k in q for k in ['g7','nato','war','conflict','sanctions','diplomatic']): return 'world'
    if any(k in q for k in ['fed','cpi','inflation','gdp','interest rate','recession']): return 'econ'
    return 'pro'

def parse_end(s):
    if not s: return None
    try: return datetime.fromisoformat(s.replace('Z', '+00:00'))
    except: return None

def market_url(slug):
    if not slug: return ''
    return f"https://polymarket.com/event/{slug}"

def should_alert(pos) -> tuple[bool, str]:
    """Filter check. Returns (pass, reason)."""
    now = datetime.now(timezone.utc)
    # Normalize everything to naive UTC for comparison
    now_naive = now.replace(tzinfo=None)

    if pos.get('redeemable'): return False, "Settled"

    end_dt = parse_end(pos.get('endDate', ''))
    if end_dt:
        end_naive = end_dt.replace(tzinfo=None) if end_dt.tzinfo else end_dt
        if end_naive < datetime(2025, 1, 1): return False, "Pre-2025 market"
        if end_naive < now_naive: return False, "Already ended"
        hours = (end_naive - now_naive).total_seconds() / 3600
        if hours < MIN_HOURS: return False, f"Ending in {int(hours)}h (<{MIN_HOURS}h)"

    price = _safe_float(pos.get('avgPrice'))
    if price <= 0: return False, "No entry price"

    # Stock ticker check
    title = pos.get('title', '')
    tickers = ['$AMAZON','$YELLEN','$GOOGL','$AAPL','$TSLA','$MSFT','$NVDA','$META','$NFLX']
    if any(t in title.upper() for t in tickers): return False, "Stock ticker"

    return True, ""

# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    conn = sqlite3.connect(DB_PATH)
    wallets = load_wallets()[:POLL_WALLETS]

    print("🐋 POLYSHARK — ENTRY TRACKER v5")
    print("=" * 50)
    print(f"📡 {len(wallets)} wallets | ⏱ {MIN_HOURS}h min | → {ALERT_GROUP_ID}")
    print()

    sent = skip = 0

    for w in wallets:
        addr = w.get('address') or ''
        if not addr: continue

        short = mask_address(addr)
        stats = get_stats(addr)
        # Enrich from seed
        seed_pnl = w.get('all_time_pnl') or w.get('total_pnl') or 0
        if stats['pnl'] == 0 and seed_pnl: stats['pnl'] = seed_pnl
        if stats['wr'] == 50: stats['wr'] = w.get('win_rate') or 50

        conn.execute('INSERT OR IGNORE INTO tracked_wallets (wallet_address) VALUES (?)', (addr,))
        conn.commit()

        print(f"📦 {short} | P&L: ${stats['pnl']:+,.0f}")

        try:
            positions = get_user_positions(addr)
            time.sleep(0.4)
            if not positions: continue

            seen = set()
            for pos in positions:
                market_id = pos.get('conditionId') or pos.get('marketId') or ''
                title = pos.get('title', 'Polymarket Position')
                slug = pos.get('slug', '')

                if market_id in seen: continue
                seen.add(market_id)
                if not market_id: continue

                # ── FILTERS (Jeff spec) ──
                ok, reason = should_alert(pos)
                ts_now = int(time.time())

                side   = pos.get('type') or pos.get('side') or 'BUY'
                price  = _safe_float(pos.get('avgPrice'))
                size   = _safe_float(pos.get('size'))
                iv     = _safe_float(pos.get('initialValue'))
                cv     = _safe_float(pos.get('currentValue'))
                cp     = _safe_float(pos.get('cashPnl'))
                amount = iv if iv > 0 else size * price
                if amount < 0.01: amount = cv

                if ok:
                    # Tiny position check
                    if cv < 50 and abs(cp) < 10 and iv < 50:
                        log_trade(conn, wallet=addr, trade_id=f"{addr[-12:]}_{market_id[-12:]}_{ts_now}",
                                  market_id=market_id, question=title, side=side.upper(),
                                  price=price, size_usdc=amount, ts_enter=ts_now)
                        print(f"  ⏭  Tiny (${cv:.2f}): {title[:40]}...")
                        skip += 1
                        continue

                    if not is_new_position(conn, addr, market_id):
                        print(f"  ⏭  Already sent: {title[:40]}...")
                        skip += 1
                        continue
                else:
                    log_trade(conn, wallet=addr, trade_id=f"{addr[-12:]}_{market_id[-12:]}_{ts_now}",
                              market_id=market_id, question=title, side=side.upper(),
                              price=price, size_usdc=amount, ts_enter=ts_now)
                    print(f"  ⏭  {reason}: {title[:40]}...")
                    skip += 1
                    continue

                # ── BUILD ALERT ──
                category = classify(title)
                ts_str   = datetime.fromtimestamp(ts_now).strftime('%b %d %H:%M')

                end_dt_raw = pos.get('endDate', '')
                hours_str = ''
                if end_dt_raw:
                    try:
                        ed = parse_end(end_dt_raw)
                        if ed:
                            ed_n = ed.replace(tzinfo=None)
                            h = int((ed_n - datetime.now().replace(tzinfo=None)).total_seconds() / 3600)
                            hours_str = f" ({h}h left)"
                    except: pass

                # Determine outcome (YES/NO from position side)
                outcome = 'YES' if side.upper() == 'BUY' else 'NO'
                entry_str = f"${price:.4f}" if price > 0 else "$0.0000"
                amount_str = f"${amount:,.2f}" if amount > 0 else "$0"

                # Caption format (Jeff spec)
                caption = f"""🐋 *WHALE ENTRY ALERT*
━━━━━━━━━━━━━━━━━━
📊 {title[:90]}
━━━━━━━━━━━━━━━━━━
📌 {side.upper()} {outcome} @ {entry_str} → {amount_str}
📅 Detected: {ts_str}{hours_str}
📁 Category: {category.upper()}
💰 Unrealized P&L: ${cp:+,.2f}
━━━━━━━━━━━━━━━━━━
👤 {short}
🔗 {market_url(slug)}
━━━━━━━━━━━━━━━━━━
_Polyshark · Real-time whale tracking_"""

                # Generate card
                img_path = f"/tmp/polyshark_alerts/entry_{addr[-8:]}_{market_id[-8:]}_{ts_now}.png"
                try:
                    make_trade_alert_card(
                        market_question = title,
                        side           = side.upper(),
                        price          = price,
                        size_usdc      = amount,
                        masked_name    = '██████████',
                        masked_wallet  = short,
                        trader_pnl     = stats['pnl'],
                        trader_wr      = stats['wr'],
                        trader_roi     = stats['roi'],
                        recent_roi     = stats['roi30d'],
                        confidence     = 'HIGH' if stats['pnl'] > 100000 or stats['wr'] > 60 else 'MEDIUM',
                        direction_arrow= '📈' if side.upper() == 'BUY' else '📉',
                        streak         = None,
                        ts_enter       = ts_now,
                        ts_exit        = None,
                        outcome        = '',
                        img_path       = img_path,
                    )
                except Exception as e:
                    print(f"  ⚠️ Card error: {e}")
                    traceback.print_exc()
                    img_path = None

                # Log before send
                log_trade(conn, wallet=addr, trade_id=f"{addr[-12:]}_{market_id[-12:]}_{ts_now}",
                          market_id=market_id, question=title, side=side.upper(),
                          price=price, size_usdc=amount, ts_enter=ts_now)

                if img_path and os.path.exists(img_path):
                    result = send_telegram(img_path, caption)
                    if result.get('ok'):
                        mark_sent(conn, addr, market_id)
                        sent += 1
                        print(f"  ✅ → {title[:45]}... | {amount_str}")
                    else:
                        print(f"  ❌ {result.get('description','error')}")
                else:
                    print(f"  ⚠️ No card: {title[:40]}")

                time.sleep(SEND_GAP)

        except Exception as e:
            print(f"  ⚠️ Error: {e}")
            traceback.print_exc()

        print()
        time.sleep(0.5)

    print(f"✅ DONE — {sent} sent | {skip} skipped+logged")
    conn.close()