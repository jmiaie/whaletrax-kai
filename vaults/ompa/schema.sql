CREATE TABLE IF NOT EXISTS channels (
    channel_id TEXT PRIMARY KEY,
    channel_name TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    owner TEXT DEFAULT '',
    notes TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS alerts (
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

CREATE INDEX IF NOT EXISTS idx_alerts_created_at ON alerts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_channel_id ON alerts(channel_id);
CREATE INDEX IF NOT EXISTS idx_alerts_market_id ON alerts(market_id);

CREATE VIEW IF NOT EXISTS v_alert_stats_total AS
SELECT
    'total' AS period_type,
    NULL AS period_start,
    NULL AS period_end,
    'all' AS scope_type,
    NULL AS scope_id,
    COUNT(*) AS alerts_count,
    SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END) AS wins_count,
    SUM(CASE WHEN result = 'loss' THEN 1 ELSE 0 END) AS losses_count,
    SUM(CASE WHEN result = 'push' THEN 1 ELSE 0 END) AS pushes_count,
    CASE WHEN SUM(CASE WHEN result IN ('win','loss') THEN 1 ELSE 0 END) > 0
         THEN ROUND(100.0 * SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END) /
                    SUM(CASE WHEN result IN ('win','loss') THEN 1 ELSE 0 END), 2)
         ELSE 0 END AS win_rate_pct,
    ROUND(SUM(profit_loss_usdc) - SUM(fees_usdc), 2) AS total_pnl_usdc,
    CASE WHEN COUNT(*) > 0 THEN ROUND((SUM(profit_loss_usdc) - SUM(fees_usdc)) / COUNT(*), 2) ELSE 0 END AS avg_pnl_usdc,
    strftime('%s','now') AS updated_at
FROM alerts;

CREATE VIEW IF NOT EXISTS v_alert_stats_month AS
SELECT
    'month' AS period_type,
    date('now','-30 day') AS period_start,
    date('now') AS period_end,
    'all' AS scope_type,
    NULL AS scope_id,
    COUNT(*) AS alerts_count,
    SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END) AS wins_count,
    SUM(CASE WHEN result = 'loss' THEN 1 ELSE 0 END) AS losses_count,
    SUM(CASE WHEN result = 'push' THEN 1 ELSE 0 END) AS pushes_count,
    CASE WHEN SUM(CASE WHEN result IN ('win','loss') THEN 1 ELSE 0 END) > 0
         THEN ROUND(100.0 * SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END) /
                    SUM(CASE WHEN result IN ('win','loss') THEN 1 ELSE 0 END), 2)
         ELSE 0 END AS win_rate_pct,
    ROUND(SUM(profit_loss_usdc) - SUM(fees_usdc), 2) AS total_pnl_usdc,
    CASE WHEN COUNT(*) > 0 THEN ROUND((SUM(profit_loss_usdc) - SUM(fees_usdc)) / COUNT(*), 2) ELSE 0 END AS avg_pnl_usdc,
    strftime('%s','now') AS updated_at
FROM alerts
WHERE created_at >= strftime('%s','now','-30 day');

CREATE VIEW IF NOT EXISTS v_alert_stats_quarter AS
SELECT
    'quarter' AS period_type,
    date('now','-90 day') AS period_start,
    date('now') AS period_end,
    'all' AS scope_type,
    NULL AS scope_id,
    COUNT(*) AS alerts_count,
    SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END) AS wins_count,
    SUM(CASE WHEN result = 'loss' THEN 1 ELSE 0 END) AS losses_count,
    SUM(CASE WHEN result = 'push' THEN 1 ELSE 0 END) AS pushes_count,
    CASE WHEN SUM(CASE WHEN result IN ('win','loss') THEN 1 ELSE 0 END) > 0
         THEN ROUND(100.0 * SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END) /
                    SUM(CASE WHEN result IN ('win','loss') THEN 1 ELSE 0 END), 2)
         ELSE 0 END AS win_rate_pct,
    ROUND(SUM(profit_loss_usdc) - SUM(fees_usdc), 2) AS total_pnl_usdc,
    CASE WHEN COUNT(*) > 0 THEN ROUND((SUM(profit_loss_usdc) - SUM(fees_usdc)) / COUNT(*), 2) ELSE 0 END AS avg_pnl_usdc,
    strftime('%s','now') AS updated_at
FROM alerts
WHERE created_at >= strftime('%s','now','-90 day');

CREATE VIEW IF NOT EXISTS v_alert_stats_year AS
SELECT
    'year' AS period_type,
    date('now','-365 day') AS period_start,
    date('now') AS period_end,
    'all' AS scope_type,
    NULL AS scope_id,
    COUNT(*) AS alerts_count,
    SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END) AS wins_count,
    SUM(CASE WHEN result = 'loss' THEN 1 ELSE 0 END) AS losses_count,
    SUM(CASE WHEN result = 'push' THEN 1 ELSE 0 END) AS pushes_count,
    CASE WHEN SUM(CASE WHEN result IN ('win','loss') THEN 1 ELSE 0 END) > 0
         THEN ROUND(100.0 * SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END) /
                    SUM(CASE WHEN result IN ('win','loss') THEN 1 ELSE 0 END), 2)
         ELSE 0 END AS win_rate_pct,
    ROUND(SUM(profit_loss_usdc) - SUM(fees_usdc), 2) AS total_pnl_usdc,
    CASE WHEN COUNT(*) > 0 THEN ROUND((SUM(profit_loss_usdc) - SUM(fees_usdc)) / COUNT(*), 2) ELSE 0 END AS avg_pnl_usdc,
    strftime('%s','now') AS updated_at
FROM alerts
WHERE created_at >= strftime('%s','now','-365 day');

CREATE VIEW IF NOT EXISTS v_channel_stats_total AS
SELECT
    'total' AS period_type,
    NULL AS period_start,
    NULL AS period_end,
    'channel' AS scope_type,
    channel_id AS scope_id,
    COUNT(*) AS alerts_count,
    SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END) AS wins_count,
    SUM(CASE WHEN result = 'loss' THEN 1 ELSE 0 END) AS losses_count,
    SUM(CASE WHEN result = 'push' THEN 1 ELSE 0 END) AS pushes_count,
    CASE WHEN SUM(CASE WHEN result IN ('win','loss') THEN 1 ELSE 0 END) > 0
         THEN ROUND(100.0 * SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END) /
                    SUM(CASE WHEN result IN ('win','loss') THEN 1 ELSE 0 END), 2)
         ELSE 0 END AS win_rate_pct,
    ROUND(SUM(profit_loss_usdc) - SUM(fees_usdc), 2) AS total_pnl_usdc,
    CASE WHEN COUNT(*) > 0 THEN ROUND((SUM(profit_loss_usdc) - SUM(fees_usdc)) / COUNT(*), 2) ELSE 0 END AS avg_pnl_usdc,
    strftime('%s','now') AS updated_at
FROM alerts
GROUP BY channel_id;
