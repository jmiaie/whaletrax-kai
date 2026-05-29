#!/usr/bin/env python3
"""Export WhaleTrax OMPA vault data to LOCUS-friendly JSON/JSONL."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT.parent.parent / 'wallet_tracker.db'
OUT_DIR = ROOT


def iso(ts: int) -> str:
    if not ts:
        return ''
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def fetch_rows(conn, sql: str):
    cur = conn.execute(sql)
    cols = [c[0] for c in cur.description]
    for row in cur.fetchall():
        yield dict(zip(cols, row))


def main() -> None:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    alerts = []
    for row in fetch_rows(conn, """
        SELECT
            id AS alert_id,
            ts_sent AS created_at,
            ts_sent AS resolved_at,
            channel_id,
            wallet_address,
            trade_id AS card_id,
            trade_id AS market_id,
            '' AS market_question,
            '' AS strategy,
            '' AS side,
            CASE WHEN status = 'sent' THEN 'win' ELSE 'push' END AS result,
            0 AS stake_usdc,
            0 AS profit_loss_usdc,
            0 AS fees_usdc,
            'trade_alerts' AS source,
            card_path AS notes,
            '{}' AS metadata_json
        FROM trade_alerts
        ORDER BY ts_sent ASC
    """):
        row['created_at_iso'] = iso(row['created_at'])
        row['resolved_at_iso'] = iso(row['resolved_at'])
        alerts.append(row)

    channels = []
    if any('channel_id' in a and a['channel_id'] for a in alerts):
        seen = {}
        for a in alerts:
            cid = a['channel_id']
            if cid and cid not in seen:
                seen[cid] = {'channel_id': cid, 'channel_name': cid, 'active': 1, 'owner': '', 'notes': ''}
        channels = list(seen.values())

    (OUT_DIR / 'alerts.jsonl').write_text('\n'.join(json.dumps(a, ensure_ascii=False) for a in alerts) + ('\n' if alerts else ''))
    (OUT_DIR / 'channels.json').write_text(json.dumps(channels, indent=2, ensure_ascii=False) + '\n')
    (OUT_DIR / 'rollups.json').write_text(json.dumps({'generated_at': datetime.now(timezone.utc).isoformat(), 'alert_count': len(alerts)}, indent=2) + '\n')

    conn.close()


if __name__ == '__main__':
    main()
