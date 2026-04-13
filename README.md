# WhaleTrax 🐋

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
