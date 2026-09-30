# WhaleTrax 🐋

> **Status (2026-09-30):** public **Kai satellite** of WhaleTrax — stalled MVP. Canonical product: private [`jmiaie/whaletrax`](https://github.com/jmiaie/whaletrax). See [`STATUS.md`](STATUS.md) and [`docs/OWNERSHIP.md`](docs/OWNERSHIP.md). No invented sniping PnL.


**WhaleTrax** is a Polymarket blockchain wallet and big-win scanner that identifies highly profitable wallets, plays, and traders on the [Polymarket](https://polymarket.com) prediction market platform.

---

## Features

- **Leaderboard Scan** – fetch and display the top Polymarket traders ranked by profit
- **Big-Win Scanner** – surface individual trades that returned the most profit / highest ROI
- **Wallet Deep Dive** – full P&L breakdown for any Polymarket proxy wallet address
- **Market Analysis** – find the top holders and whale trades inside a specific market

Data is sourced from Polymarket's public APIs:

| API | Base URL | Used for |
|-----|----------|----------|
| Gamma API | `https://gamma-api.polymarket.com` | Market metadata, prices |
| Data API  | `https://data-api.polymarket.com`  | Trades, positions, leaderboard |
| CLOB API  | `https://clob.polymarket.com`      | Order book, recent trades |

No API keys are required for read-only access.

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. (Optional) Configure thresholds

```bash
cp .env.example .env
# Edit .env to adjust big-win thresholds, pagination limits, etc.
```

### 3. Run the scanner

```bash
# Show the top-20 traders on the leaderboard
python main.py scan-leaderboard

# Expand to top-50 and include big-win counts
python main.py scan-leaderboard --top 50

# Find the biggest single-trade wins across the top-50 wallets
python main.py scan-big-wins --top 50

# Lower thresholds to see more wins
python main.py scan-big-wins --min-profit 200 --min-roi 30 --min-size 50

# Deep dive on a specific wallet
python main.py scan-wallet 0xYourPolymarketProxyAddress

# Analyse a specific market (use the Polymarket condition ID)
python main.py scan-market 0xMarketConditionId

# Get help
python main.py --help
python main.py scan-big-wins --help
```

---

## CLI Reference

### `scan-leaderboard`

Fetches the Polymarket profit leaderboard and displays a ranked table.

| Option | Default | Description |
|--------|---------|-------------|
| `--top N` | 20 | Number of top wallets to show |
| `--big-wins / --no-big-wins` | `--big-wins` | Include big-win counts per wallet |

### `scan-big-wins`

Scans the top-N leaderboard wallets and lists every trade that qualifies as a "big win".

A trade is a **big win** when:
- Realised profit ≥ `--min-profit` USDC (default 500)
- ROI ≥ `--min-roi` % (default 50 %)
- Trade cost basis ≥ `--min-size` USDC (default 100)

| Option | Default | Description |
|--------|---------|-------------|
| `--top N` | 50 | Wallets to scan |
| `--min-profit` | 500 | Minimum USDC profit |
| `--min-roi` | 50 | Minimum ROI % |
| `--min-size` | 100 | Minimum trade size USDC |

### `scan-wallet <address>`

Deep-dive analysis of a single Polymarket proxy wallet.

> **Note:** Polymarket uses Gnosis Safe proxy wallets. Use the proxy address (shown in your Polymarket profile URL), not your MetaMask EOA.

| Option | Default | Description |
|--------|---------|-------------|
| `--big-wins / --no-big-wins` | `--big-wins` | Show individual big-win trades |

### `scan-market <market_id>`

Find top holders and whale trades for a specific prediction market.

| Option | Default | Description |
|--------|---------|-------------|
| `--top-holders N` | 20 | Number of top holders to display |
| `--big-wins / --no-big-wins` | `--big-wins` | Scan big wins from top holders |

---

## Configuration

All settings can be overridden via a `.env` file (see `.env.example`) or environment variables.

| Variable | Default | Description |
|----------|---------|-------------|
| `GAMMA_API_BASE` | `https://gamma-api.polymarket.com` | Gamma API URL |
| `DATA_API_BASE` | `https://data-api.polymarket.com` | Data API URL |
| `CLOB_API_BASE` | `https://clob.polymarket.com` | CLOB API URL |
| `REQUEST_TIMEOUT` | `30` | HTTP timeout (seconds) |
| `MAX_RETRIES` | `3` | HTTP retry attempts |
| `BIG_WIN_MIN_PROFIT_USDC` | `500` | Big-win profit threshold |
| `BIG_WIN_MIN_ROI_PCT` | `50` | Big-win ROI threshold (%) |
| `BIG_WIN_MIN_TRADE_SIZE_USDC` | `100` | Big-win minimum trade size |
| `LEADERBOARD_TOP_N` | `50` | Default leaderboard size |
| `DISPLAY_TOP_N` | `20` | Default display rows |

---

## Project Structure

```
whaletrax/
├── main.py                  # CLI entry point (Click)
├── requirements.txt         # Python dependencies
├── .env.example             # Environment variable template
└── src/
    ├── config.py            # All configuration constants
    ├── models.py            # Data models (Trade, Position, WalletStats, BigWin)
    ├── polymarket_client.py # Polymarket API wrapper (Gamma, Data, CLOB)
    ├── wallet_scanner.py    # Leaderboard + wallet P&L logic
    ├── big_win_detector.py  # Big-win detection logic
    └── display.py           # Rich terminal tables & panels
```

---

## Notes

- Polymarket enforces rate limits on its public APIs. The scanner includes automatic retry with exponential backoff.
- The scanner reads **closed positions / resolved trades** to compute realised P&L. Open positions show unrealised P&L only.
- Wallet addresses on Polymarket are proxy (smart contract) wallets, not your EOA. You can find yours in your Polymarket profile URL: `https://polymarket.com/profile/{proxyAddress}`.

---

## WalletHound 🐕

**WalletHound** is WhaleTrax's advanced wallet-tracking feature set that goes beyond basic leaderboard scanning. It identifies three distinct categories of impressive Polymarket wallets:

| Category | Emoji | What it detects |
|----------|-------|----------------|
| **Big Winners** | 🏆 | Wallets with large single-trade wins (high profit & ROI) |
| **Consistent Winners** | 🎯 | Wallets that win reliably — high win rates, long streaks, strong profit factors |
| **Compounders** | 📈 | Wallets growing balances through compounding wins (deposits don't count) |

### Key Accounting Principle

WalletHound tracks **wins only** — deposits don't count as balance growth. Both deposits and withdrawals are accounted for to ensure accuracy. Organic growth is always separated from external funding.

### WalletHound CLI

All WalletHound commands are grouped under `python main.py wallethound`:

```bash
# Full scan — find big winners, consistent winners, and compounders
python main.py wallethound scan --top 20

# Filter by tier
python main.py wallethound scan --tier big_winner
python main.py wallethound scan --tier consistent_winner
python main.py wallethound scan --tier compounder

# Deep-dive on a single wallet
python main.py wallethound wallet 0xYourPolymarketProxyAddress

# Find consistent winners specifically
python main.py wallethound consistent --top 50 --min-score 60

# Find compounders specifically
python main.py wallethound compounders --top 50 --min-score 50 --min-growth 20

# Start the web dashboard
python main.py wallethound web --port 5000

# Get help
python main.py wallethound --help
```

#### `wallethound scan`

Scans the top-N leaderboard wallets through all three detectors and classifies them.

| Option | Default | Description |
|--------|---------|-------------|
| `--top N` | 50 | Number of wallets to scan |
| `--tier` | (all) | Filter: `big_winner`, `consistent_winner`, or `compounder` |

#### `wallethound wallet <address>`

Full WalletHound analysis of a single wallet — shows trading stats, consistency score, organic growth, and deposit/withdrawal accounting.

#### `wallethound consistent`

Finds wallets with the highest consistency scores.

| Option | Default | Description |
|--------|---------|-------------|
| `--top N` | 50 | Number of wallets to scan |
| `--min-score` | 50 | Minimum consistency score (0–100) |

The consistency score is a composite of:
- **Win rate** (40%) — percentage of winning trades
- **Profit factor** (25%) — gross wins / gross losses
- **Longest win streak** (20%) — consecutive winning trades
- **Trade count confidence** (15%) — more trades = more statistically meaningful

#### `wallethound compounders`

Finds wallets growing their balances through compounding wins.

| Option | Default | Description |
|--------|---------|-------------|
| `--top N` | 50 | Number of wallets to scan |
| `--min-score` | 40 | Minimum compounding score (0–100) |
| `--min-growth` | 10 | Minimum organic growth % |

#### `wallethound web`

Starts the WalletHound web dashboard.

| Option | Default | Description |
|--------|---------|-------------|
| `--port` | 5000 | Port to serve the dashboard on |
| `--debug / --no-debug` | `--no-debug` | Enable Flask debug mode |

### WalletHound Web Dashboard

The web dashboard provides a browser-based interface with:

- **Dashboard** — overview of all tracked wallets with summary cards, tier distribution chart, and profit chart
- **Big Winners** — table of the largest single-trade wins
- **Consistent Winners** — table of the most consistent winning wallets
- **Compounders** — table of wallets growing through wins (deposits excluded)
- **Wallet Detail** — deep-dive analysis of any wallet address
- **REST API** — JSON endpoints for programmatic access

#### REST API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/hound/scan?top=N&tier=...` | GET | Full WalletHound scan |
| `/api/hound/wallet/<address>` | GET | Single wallet analysis |
| `/api/big-winners?top=N` | GET | Big-winner trades |
| `/api/consistent-winners?top=N&min_score=50` | GET | Consistent winners |
| `/api/compounders?top=N&min_score=40&min_growth=10` | GET | Compounders |

### WalletHound Project Structure

```
src/wallethound/
├── __init__.py
├── models.py              # WalletHound data models
├── deposit_tracker.py     # Deposit/withdrawal detection & accounting
├── consistent_winners.py  # Consistency scoring engine
├── compounders.py         # Compounder detection (organic growth only)
├── scanner.py             # Main orchestrator
└── display.py             # Rich terminal display helpers

wallethound_web/
├── __init__.py
├── app.py                 # Flask application & REST API
├── templates/
│   ├── base.html          # Base layout with navbar
│   ├── index.html         # Dashboard landing page
│   ├── big_winners.html   # Big winners page
│   ├── consistent_winners.html
│   ├── compounders.html
│   └── wallet_detail.html # Single wallet deep-dive
└── static/
    ├── css/style.css      # Custom styles
    └── js/dashboard.js    # Dashboard interactivity & charts
```
