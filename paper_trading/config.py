# Paper Trading Config — Polyshark
# Simulation parameters for backtesting whale copy-trade strategies

# ── Exchange / Market assumptions ───────────────────────────
SLIPPAGE_BUFFER = 0.015   # 1.5% slippage on entry (conservative)
MIN_POSITION_USD = 10    # minimum trade size to consider
MAX_POSITION_USD = 50_000  # hard cap per signal

# ── Strategy sizing tiers ──────────────────────────────────
# Fraction of signal wallet's position size we replicate
TOP1_COPY_PCT   = 1.00   # 100% of top-1 signal size
TOP3_COPY_PCT   = 0.50   # 50% of top-3 signal size  
TOP20_COPY_PCT   = 0.25   # 25% of top-20 signal size
FREE_COPY_PCT    = 0.10   # 10% for free-tier signals

# ── Entry / Exit rules ─────────────────────────────────────
ENTRY_MODE = "entry_price"   # "entry_price" = at signal price, "clob_price" = live CLOB mid
EXIT_MODE  = "resolve"      # "resolve" = hold to market close, "partial_close" = early exit
PARTIAL_CLOSE_HRS = 4       # exit early if position is >X hrs old and profitable >threshold
PARTIAL_PROFIT_PCT = 0.50   # take profit at +50% of potential profit

# ── Filters ────────────────────────────────────────────────
MIN_WIN_RATE   = 50.0    # skip wallets below this WR
MIN_POSITIONS   = 10       # skip wallets with fewer lifetime positions
SKIP_CLOSED     = True     # skip markets already resolved at signal time

# ── Position caps ───────────────────────────────────────────
MAX_CONCURRENT_TRADES = 10   # max open positions at once
MAX_LOSS_PER_TRADE     = 100 # stop-loss: exit if loss exceeds this USD
DAILY_LOSS_CAP         = 500 # stop trading if daily loss exceeds this

# ── Output ──────────────────────────────────────────────────
PAPER_LEDGER_FILE = "/home/ubuntu/.openclaw/workspace/repos/whaletrax/paper_trading/ledger.json"
RESULTS_DIR       = "/home/ubuntu/.openclaw/workspace/repos/whaletrax/paper_trading/results"