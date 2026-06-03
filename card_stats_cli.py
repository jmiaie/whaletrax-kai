#!/usr/bin/env python3
"""
card_stats_cli.py — Query the card stats DB.
Usage:
  python3 card_stats_cli.py today
  python3 card_stats_cli.py week
  python3 card_stats_cli.py categories
  python3 card_stats_cli.py sample
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from card_stats import get_daily_counts, get_category_breakdown
import json, time

def fmt(d):
    return json.dumps(d, indent=2)

if len(sys.argv) < 2:
    print(__doc__)
    sys.exit(0)

cmd = sys.argv[1]

if cmd == "today":
    print("=== Today ===")
    counts = get_daily_counts()
    print(fmt(counts) if counts else "{}")

elif cmd == "week":
    print("=== Last 7 days by category ===")
    rows = get_category_breakdown(days=7)
    total = sum(r["cnt"] for r in rows)
    print(f"Total cards: {total}")
    print(fmt(rows) if rows else "[]")

elif cmd == "categories":
    print("=== All categories (all time) ===")
    import sqlite3
    c = sqlite3.connect(Path(__file__).parent / "card_stats.db", timeout=30)
    c.row_factory = sqlite3.Row
    rows = c.execute(
        "SELECT category, COUNT(*) as cnt FROM cards GROUP BY category ORDER BY cnt DESC"
    ).fetchall()
    c.close()
    total = sum(r["cnt"] for r in rows)
    print(f"Total cards: {total}")
    print(fmt([dict(r) for r in rows]) if rows else "[]")

elif cmd == "sample":
    print("=== Recent cards ===")
    import sqlite3
    c = sqlite3.connect(Path(__file__).parent / "card_stats.db", timeout=30)
    c.row_factory = sqlite3.Row
    rows = c.execute(
        "SELECT date_, tier, category, question FROM cards ORDER BY sent_at DESC LIMIT 10"
    ).fetchall()
    c.close()
    for r in rows:
        print(f"  {r['date_']} [{r['tier']}] [{r['category']}] {r['question'][:60]}")

elif cmd == "all":
    print("=== Daily totals (all time) ===")
    import sqlite3
    c = sqlite3.connect(Path(__file__).parent / "card_stats.db", timeout=30)
    c.row_factory = sqlite3.Row
    rows = c.execute(
        "SELECT * FROM daily_sums ORDER BY date_ DESC LIMIT 30"
    ).fetchall()
    c.close()
    print(fmt([dict(r) for r in rows]) if rows else "[]")

else:
    print(f"Unknown command: {cmd}")
    print(__doc__)