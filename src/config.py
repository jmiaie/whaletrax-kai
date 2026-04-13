"""
Configuration constants for WhaleTrax.
All thresholds and API base URLs are defined here; override via environment variables.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── API base URLs ────────────────────────────────────────────────────────────
GAMMA_API_BASE = os.getenv("GAMMA_API_BASE", "https://gamma-api.polymarket.com")
DATA_API_BASE = os.getenv("DATA_API_BASE", "https://data-api.polymarket.com")
CLOB_API_BASE = os.getenv("CLOB_API_BASE", "https://clob.polymarket.com")

# ── HTTP settings ────────────────────────────────────────────────────────────
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
RETRY_BACKOFF = float(os.getenv("RETRY_BACKOFF", "1.5"))  # seconds between retries

# ── Pagination defaults ──────────────────────────────────────────────────────
DEFAULT_PAGE_LIMIT = int(os.getenv("DEFAULT_PAGE_LIMIT", "100"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "10"))  # max pages to fetch per query

# ── Big-win detection thresholds ─────────────────────────────────────────────
# A trade is a "big win" when ALL of the following are met:
BIG_WIN_MIN_PROFIT_USDC = float(os.getenv("BIG_WIN_MIN_PROFIT_USDC", "500"))
BIG_WIN_MIN_ROI_PCT = float(os.getenv("BIG_WIN_MIN_ROI_PCT", "50"))   # percent
BIG_WIN_MIN_TRADE_SIZE_USDC = float(os.getenv("BIG_WIN_MIN_TRADE_SIZE_USDC", "100"))

# ── Leaderboard / wallet scan settings ───────────────────────────────────────
LEADERBOARD_TOP_N = int(os.getenv("LEADERBOARD_TOP_N", "50"))
WALLET_SCAN_MAX_TRADES = int(os.getenv("WALLET_SCAN_MAX_TRADES", "500"))

# ── Market scan settings ──────────────────────────────────────────────────────
MARKET_TOP_HOLDERS_N = int(os.getenv("MARKET_TOP_HOLDERS_N", "20"))

# ── Display ───────────────────────────────────────────────────────────────────
DISPLAY_TOP_N = int(os.getenv("DISPLAY_TOP_N", "20"))
