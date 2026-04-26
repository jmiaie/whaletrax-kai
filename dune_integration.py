#!/usr/bin/env python3
"""
Whaletrax Dune Integration
Uses Dune API to pull Polymarket whale data for Polyshark watchlist
"""

import os
from dune_client.client import DuneClient
from dune_client.query import QueryBase

# Load Jeff's Dune API key
DUNE_API_KEY = os.getenv("DUNE_API_KEY") or open("/home/ubuntu/.openclaw/workspace/credentials/skey-dune-jefe").read().strip()

dune = DuneClient(DUNE_API_KEY)

# Polymarket-related query IDs (common public Dune queries for Polymarket)
# These are placeholder IDs - we need to find the actual public query IDs
POLYMARKET_LEADERBOARD_QUERY_ID = 1215383  # placeholder
POLYMARKET_TOP_TRADERS_QUERY_ID = 1215383  # placeholder

def get_polymarket_wallets():
    """Pull Polymarket trader data from Dune public queries."""
    results = dune.get_latest_result(POLYMARKET_LEADERBOARD_QUERY_ID, max_age_hours=24)
    print("Results:", results)
    return results

if __name__ == "__main__":
    print(f"Dune Client configured with key: {DUNE_API_KEY[:8]}...")
    print(get_polymarket_wallets())