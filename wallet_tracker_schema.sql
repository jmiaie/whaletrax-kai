-- Polyshark Wallet Tracker Schema
-- Tracks: trades, positions, alerts, wallet stats

CREATE TABLE IF NOT EXISTS tracked_wallets (
    wallet_address TEXT PRIMARY KEY,
    display_name   TEXT DEFAULT '',
    tier           TEXT DEFAULT 'whale',  -- whale | preferred | vip
    is_active      INTEGER DEFAULT 1,
    added_at       INTEGER DEFAULT (unixepoch()),
    last_seen      INTEGER DEFAULT 0,
    total_trades   INTEGER DEFAULT 0,
    total_pnl      REAL DEFAULT 0,
    win_rate_pct   REAL DEFAULT 0,
    roi_pct        REAL DEFAULT 0,
    roi_30d        REAL DEFAULT 0,
    streak_current INTEGER DEFAULT 0,
    streak_best    INTEGER DEFAULT 0,
    last_trade_id  TEXT DEFAULT ''   -- hash of last trade to detect new trades
);

CREATE TABLE IF NOT EXISTS wallet_trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address  TEXT NOT NULL,
    trade_id        TEXT UNIQUE NOT NULL,  -- Polymarket trade ID
    market_id       TEXT DEFAULT '',
    market_question TEXT DEFAULT '',
    side            TEXT NOT NULL,          -- buy | sell
    outcome         TEXT DEFAULT '',         -- yes | no | pending
    entry_price     REAL DEFAULT 0,
    size_usdc       REAL DEFAULT 0,
    realized_pnl    REAL DEFAULT 0,         -- filled when position closes
    ts_enter        INTEGER NOT NULL,
    ts_exit         INTEGER DEFAULT 0,      -- 0 = still open
    ts_created      INTEGER DEFAULT (unixepoch()),
    is_closed       INTEGER DEFAULT 0,
    alert_sent      INTEGER DEFAULT 0,      -- 1 = alert was sent to Telegram
    alert_sent_at   INTEGER DEFAULT 0,
    FOREIGN KEY (wallet_address) REFERENCES tracked_wallets(wallet_address)
);

CREATE TABLE IF NOT EXISTS wallet_positions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address  TEXT NOT NULL,
    market_id       TEXT UNIQUE NOT NULL,
    market_question TEXT DEFAULT '',
    side            TEXT NOT NULL,
    entry_price     REAL DEFAULT 0,
    size_usdc       REAL DEFAULT 0,
    current_price   REAL DEFAULT 0,
    unrealized_pnl  REAL DEFAULT 0,
    ts_enter        INTEGER NOT NULL,
    ts_last_seen    INTEGER DEFAULT (unixepoch()),
    FOREIGN KEY (wallet_address) REFERENCES tracked_wallets(wallet_address)
);

CREATE TABLE IF NOT EXISTS trade_alerts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address  TEXT NOT NULL,
    trade_id        TEXT NOT NULL,
    channel_id      TEXT NOT NULL,           -- where it was sent
    ts_sent         INTEGER DEFAULT (unixepoch()),
    card_path       TEXT DEFAULT '',
    alert_type      TEXT DEFAULT 'entry',    -- entry | exit | signal
    status          TEXT DEFAULT 'sent'      -- sent | failed | pending
);

CREATE TABLE IF NOT EXISTS wallet_stats_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address  TEXT NOT NULL,
    snapshot_date   INTEGER NOT NULL,        -- date as YYYYMMDD
    total_trades    INTEGER DEFAULT 0,
    win_count       INTEGER DEFAULT 0,
    loss_count      INTEGER DEFAULT 0,
    total_pnl       REAL DEFAULT 0,
    win_rate_pct    REAL DEFAULT 0,
    roi_pct         REAL DEFAULT 0,
    roi_30d         REAL DEFAULT 0,
    streak_current  INTEGER DEFAULT 0,
    UNIQUE(wallet_address, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_trades_wallet    ON wallet_trades(wallet_address);
CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON wallet_trades(ts_enter DESC);
CREATE INDEX IF NOT EXISTS idx_trades_market    ON wallet_trades(market_id);
CREATE INDEX IF NOT EXISTS idx_positions_wallet ON wallet_positions(wallet_address);
CREATE INDEX IF NOT EXISTS idx_alerts_wallet    ON trade_alerts(wallet_address);