#!/usr/bin/env python3
"""Build top-20 wallet analysis DB and CSV from wallet_profiles.json."""
import json, sqlite3, csv, statistics
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('/home/ubuntu/.openclaw/workspace')
REPO = ROOT / 'repos/whaletrax'
REPO.mkdir(parents=True, exist_ok=True)

with open('/tmp/wallet_profiles.json') as f:
    wallets = json.load(f)

wr100 = {addr: w for addr, w in wallets.items()
         if w.get('win_rate') == 100.0 and w.get('total_positions', 0) >= 10}

sorted_wallets = sorted(wr100.items(), key=lambda x: x[1].get('total_pnl', 0), reverse=True)
top20 = sorted_wallets[:20]

DB = REPO / 'top_wallets.db'
conn = sqlite3.connect(str(DB))
cur = conn.cursor()

cur.execute('''CREATE TABLE IF NOT EXISTS wallets (
    rank INTEGER PRIMARY KEY, addr TEXT, name TEXT, win_rate REAL,
    total_positions INTEGER, total_pnl REAL, avg_size REAL, max_position REAL,
    min_position REAL, avg_mult REAL, std_mult REAL, min_mult REAL, max_mult REAL,
    pnl_per_trade REAL, roi_pct REAL, span_days INTEGER,
    first_trade TEXT, last_trade TEXT, risk_score TEXT
)''')
cur.execute('DELETE FROM wallets')

cur.execute('''CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, wallet_addr TEXT, ts INTEGER,
    ts_date TEXT, pnl REAL, sz REAL, mult REAL
)''')
cur.execute('DELETE FROM positions')

wallet_rows, pos_rows = [], []
for rank, (addr, w) in enumerate(top20, 1):
    ph = w.get('_pos_history', [])
    sizes = [p.get('sz', 0) for p in ph]
    pnl_vals = [p.get('pnl', 0) or 0 for p in ph]
    muls = [(p.get('pnl', 0) or 0) / max(p.get('sz', 0.01), 0.01) for p in ph]

    first_ts = ph[0]['ts'] if ph else 0
    last_ts = ph[-1]['ts'] if ph else 0
    span_days = int((last_ts - first_ts) / 86400) if first_ts and last_ts else 0

    avg_mult = statistics.mean(muls) if muls else 0
    std_mult = statistics.stdev(muls) if len(muls) > 1 else 0
    total_invested = sum(sizes)
    roi = (w.get('total_pnl', 0) / total_invested * 100) if total_invested > 0 else 0
    risk = 'LOW' if std_mult < 0.1 else ('MEDIUM' if std_mult < 0.25 else 'HIGH')
    first_dt = datetime.fromtimestamp(first_ts, tz=timezone.utc).strftime('%Y-%m-%d') if first_ts else 'N/A'
    last_dt = datetime.fromtimestamp(last_ts, tz=timezone.utc).strftime('%Y-%m-%d') if last_ts else 'N/A'

    wallet_rows.append((rank, addr, w.get('name', ''), w.get('win_rate', 0),
        w.get('total_positions', 0), w.get('total_pnl', 0), w.get('avg_size', 0),
        max(sizes) if sizes else 0, min(sizes) if sizes else 0,
        avg_mult, std_mult, min(muls) if muls else 0, max(muls) if muls else 0,
        sum(pnl_vals) / max(len(ph), 1), roi, span_days, first_dt, last_dt, risk))

    for p in ph:
        dt = datetime.fromtimestamp(p['ts'], tz=timezone.utc)
        m = (p.get('pnl', 0) or 0) / max(p.get('sz', 0.01), 0.01)
        pos_rows.append((addr, int(p['ts']), dt.strftime('%Y-%m-%d'),
                         p.get('pnl', 0) or 0, p.get('sz', 0) or 0, m))

csv_path = REPO / 'top20_wallets.csv'
with open(csv_path, 'w', newline='') as f:
    w2 = csv.writer(f)
    w2.writerow(['Rank','Wallet','Name','WR%','Trades','Total PnL','Avg Size','Max Size',
                 'Min Size','Avg Mult','Std Mult','Min Mult','Max Mult','PnL/Trade',
                 'ROI%','Span Days','First Trade','Last Trade','Risk'])
    w2.writerows(wallet_rows)

print(f"DB: {DB} ({conn.execute('SELECT COUNT(*) FROM wallets').fetchone()[0]} wallets, "
      f"{conn.execute('SELECT COUNT(*) FROM positions').fetchone()[0]} positions)")
print(f"CSV: {csv_path}")

# Print ranked table
print(f"\n{'Rk':<3} {'Addr':<22} {'PnL':>14} {'Trades':>7} {'AvgMult':>9} {'StdDev':>8} {'Risk':<8}")
print("-" * 80)
for r in wallet_rows:
    print(f"  {r[0]:<2} {r[1][:20]:<20} ${r[5]:>12,.0f} {r[4]:>7} {r[9]:>9.4f} {r[10]:>8.4f} {r[18]:<8}")

conn.close()