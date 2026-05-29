#!/usr/bin/env python3
"""Generate OMPA rollups from the ingested alert ledger."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT.parent.parent / 'wallet_tracker.db'
OUT_PATH = ROOT / 'rollups.json'


def main() -> None:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    def fetch(sql: str):
        cur = conn.execute(sql)
        row = cur.fetchone()
        return dict(row) if row else {}

    payload = {
        'generated_at': datetime.now(tz=timezone.utc).isoformat(),
        'overall': {
            'total': fetch('SELECT * FROM v_alert_stats_total'),
            'month': fetch('SELECT * FROM v_alert_stats_month'),
            'quarter': fetch('SELECT * FROM v_alert_stats_quarter'),
            'year': fetch('SELECT * FROM v_alert_stats_year'),
        },
        'channels': {
            'total': [dict(r) for r in conn.execute('SELECT * FROM v_channel_stats_total ORDER BY total_pnl_usdc DESC, win_rate_pct DESC').fetchall()],
            'month': [dict(r) for r in conn.execute('SELECT * FROM v_channel_stats_month ORDER BY total_pnl_usdc DESC, win_rate_pct DESC').fetchall()],
            'quarter': [dict(r) for r in conn.execute('SELECT * FROM v_channel_stats_quarter ORDER BY total_pnl_usdc DESC, win_rate_pct DESC').fetchall()],
            'year': [dict(r) for r in conn.execute('SELECT * FROM v_channel_stats_year ORDER BY total_pnl_usdc DESC, win_rate_pct DESC').fetchall()],
        },
    }

    OUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n')
    conn.close()
    print(json.dumps({'wrote': str(OUT_PATH)}))


if __name__ == '__main__':
    main()
