import json, os
from src.polymarket_client import get_leaderboard

LEADERBOARD_STATE_FILE = '/tmp/whaletrax_leaderboard_state.json'
WATCH_KEY = '0x63a51cbb37341837b873bc29d05f482bc2988e33'.lower()

def load_prev_state():
    if os.path.exists(LEADERBOARD_STATE_FILE):
        return json.load(open(LEADERBOARD_STATE_FILE)).get('wallets', {})
    return {}

def save_state(wallets):
    with open(LEADERBOARD_STATE_FILE, 'w') as f:
        json.dump({'wallets': wallets, 'ts': __import__('datetime').datetime.now().isoformat()}, f)

def detect_changes(top_n=20):
    """Returns (alerts, new_state) where alerts is a list of strings describing changes."""
    entries = get_leaderboard(limit=top_n)
    new_wallets = {}
    for e in entries:
        addr = e.get('proxyWallet', '').lower()
        if addr:
            new_wallets[addr] = {
                'rank': e.get('rank'),
                'vol': e.get('vol'),
                'pnl': e.get('pnl'),
                'name': e.get('userName', '')
            }

    prev = load_prev_state()
    alerts = []

    for addr, info in new_wallets.items():
        rank = info['rank']
        prev_info = prev.get(addr)

        if addr not in prev:
            # New entrant
            badge = '\U0001f3c6 HIGH-FREQ WINNING WHALE \U0001f3c6' if addr == WATCH_KEY else '\U0001f525 NEW LEADERBOARD ENTRY'
            alerts.append(f'{badge}\n\U0001f4ca Rank #{rank} | {info["name"] or "Unknown"}\n\U0001f4b0 ${float(info["vol"] or 0):,.0f} vol | ${float(info["pnl"] or 0):,.0f} PnL')
        elif prev_info and int(rank) < int(prev_info.get('rank', 99)):
            # Rank improved
            prev_rank = prev_info.get('rank', '?')
            alerts.append(f'\U0001f3c6 RANK UP: #{prev_rank} \u2192 #{rank} | {info["name"] or addr[:8]}...\n\U0001f4b0 $vol: ${float(info["vol"] or 0):,.0f} | $PnL: ${float(info["pnl"] or 0):,.0f}')

    # Wallets that dropped out
    dropped = set(prev.keys()) - set(new_wallets.keys())
    for addr in dropped:
        pi = prev[addr]
        badge = ' (HIGH-FREQ WINNING WHALE)' if addr == WATCH_KEY else ''
        alerts.append(f'\U0001f6ab DROPPED from top {top_n}\nRank #{pi.get("rank")} | {pi.get("name") or addr[:8]}...{badge}')

    save_state(new_wallets)
    return alerts

if __name__ == '__main__':
    import sys
    token = '8741871021:AAFI3bRTTSurnjMgY32AAPSPtoozb1eji_g'
    token = '8741871021:AAFI3bRTTSurnjMgY32AAPSPtoozb1eji_g'
    CHAT = -1003786930778

    import requests
    alerts = detect_changes()
    if alerts:
        text = '\n\n'.join(['\U0001f525 LEADERBOARD UPDATE\n'] + alerts[:5])
        r = requests.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            json={'chat_id': CHAT, 'text': text, 'parse_mode': 'HTML', 'disable_web_page_preview': True},
            timeout=15
        )
        print('Sent' if r.json().get('ok') else r.json())
    else:
        print('No changes')