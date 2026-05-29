-- WhaleTrax OMPA reporting queries
-- Rolling windows: 30 / 90 / 365 days

CREATE VIEW IF NOT EXISTS v_alert_stats_month AS
SELECT
    'month' AS period_type,
    datetime('now','-30 day') AS period_start,
    datetime('now') AS period_end,
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
FROM ompa_alerts
WHERE created_at >= strftime('%s','now','-30 day');

CREATE VIEW IF NOT EXISTS v_alert_stats_quarter AS
SELECT
    'quarter' AS period_type,
    datetime('now','-90 day') AS period_start,
    datetime('now') AS period_end,
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
FROM ompa_alerts
WHERE created_at >= strftime('%s','now','-90 day');

CREATE VIEW IF NOT EXISTS v_alert_stats_year AS
SELECT
    'year' AS period_type,
    datetime('now','-365 day') AS period_start,
    datetime('now') AS period_end,
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
FROM ompa_alerts
WHERE created_at >= strftime('%s','now','-365 day');

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
FROM ompa_alerts;

CREATE VIEW IF NOT EXISTS v_channel_stats_month AS
SELECT
    'month' AS period_type,
    datetime('now','-30 day') AS period_start,
    datetime('now') AS period_end,
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
FROM ompa_alerts
WHERE created_at >= strftime('%s','now','-30 day')
GROUP BY channel_id;

CREATE VIEW IF NOT EXISTS v_channel_stats_quarter AS
SELECT
    'quarter' AS period_type,
    datetime('now','-90 day') AS period_start,
    datetime('now') AS period_end,
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
FROM ompa_alerts
WHERE created_at >= strftime('%s','now','-90 day')
GROUP BY channel_id;

CREATE VIEW IF NOT EXISTS v_channel_stats_year AS
SELECT
    'year' AS period_type,
    datetime('now','-365 day') AS period_start,
    datetime('now') AS period_end,
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
FROM ompa_alerts
WHERE created_at >= strftime('%s','now','-365 day')
GROUP BY channel_id;

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
FROM ompa_alerts
GROUP BY channel_id;
