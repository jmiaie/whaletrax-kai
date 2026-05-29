#!/usr/bin/env python3
"""Ingest WhaleTrax tracker data into the OMPA vault."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT.parent.parent / 'wallet_tracker.db'


def now_ts() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp())


def ensure_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS ompa_channels (
            channel_id TEXT PRIMARY KEY,
            channel_name TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            owner TEXT DEFAULT '',
            notes TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS ompa_alerts (
            alert_id TEXT PRIMARY KEY,
            created_at INTEGER NOT NULL,
            resolved_at INTEGER DEFAULT 0,
            channel_id TEXT DEFAULT '',
            route TEXT DEFAULT '',
            card_id TEXT DEFAULT '',
            market_id TEXT DEFAULT '',
            market_question TEXT DEFAULT '',
            strategy TEXT DEFAULT '',
            side TEXT DEFAULT '',
            result TEXT NOT NULL DEFAULT 'push',
            stake_usdc REAL NOT NULL DEFAULT 0,
            profit_loss_usdc REAL NOT NULL DEFAULT 0,
            fees_usdc REAL NOT NULL DEFAULT 0,
            source TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            metadata_json TEXT DEFAULT '{}'
        );
        """
    )


def ingest_trade_alerts(conn: sqlite3.Connection) -> int:
    cur = conn.execute(
        """
        SELECT id, wallet_address, trade_id, channel_id, ts_sent, card_path, alert_type, status
        FROM trade_alerts
        ORDER BY ts_sent ASC
        """
    )
    rows = cur.fetchall()
    inserted = 0
    for r in rows:
        alert_id = f"trade_alert:{r['id']}"
        metadata = {
            'wallet_address': r['wallet_address'],
            'alert_type': r['alert_type'],
            'status': r['status'],
            'source_table': 'trade_alerts',
        }
        conn.execute(
            """
            INSERT OR REPLACE INTO ompa_alerts (
                alert_id, created_at, resolved_at, channel_id, route, card_id, market_id,
                market_question, strategy, side, result, stake_usdc, profit_loss_usdc,
                fees_usdc, source, notes, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alert_id,
                int(r['ts_sent'] or now_ts()),
                int(r['ts_sent'] or now_ts()),
                r['channel_id'] or '',
                r['channel_id'] or '',
                r['trade_id'] or '',
                r['trade_id'] or '',
                '',
                '',
                '',
                'win' if (r['status'] or '') == 'sent' else 'push',
                0,
                0,
                0,
                'trade_alerts',
                r['card_path'] or '',
                json.dumps(metadata),
            ),
        )
        inserted += 1
        if r['channel_id']:
            conn.execute(
                "INSERT OR IGNORE INTO ompa_channels (channel_id, channel_name) VALUES (?, ?)",
                (r['channel_id'], r['channel_id']),
            )
    return inserted


def main() -> None:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    ensure_tables(conn)
    inserted = ingest_trade_alerts(conn)
    conn.commit()
    print(json.dumps({'ingested': inserted, 'ts': now_ts()}))
    conn.close()


if __name__ == '__main__':
    main()
