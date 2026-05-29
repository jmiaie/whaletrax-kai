# WhaleTrax OMPA Vault Design

## Goal
Create a private, team-shared vault inside Whaletrax that tracks all alert/card outcomes and computes:
- Total WR
- Annual WR
- Quarterly WR
- Monthly WR
- Total P/L
- Annual / Quarterly / Monthly P/L
- Per-channel WR and P/L

## Recommended storage
Use one append-only event log plus derived rollups.

### Core tables
#### alerts
One row per alert/card outcome.
- alert_id (PK)
- created_at
- resolved_at
- channel
- route
- card_id
- market_id
- market_question
- strategy
- side
- result (win|loss|push)
- stake_usdc
- profit_loss_usdc
- fees_usdc
- source
- notes
- metadata_json

#### channels
Optional lookup table.
- channel_id (PK)
- channel_name
- active
- owner
- notes

#### alert_rollups
Materialized summary by period.
- period_type (total|year|quarter|month)
- period_start
- period_end
- scope_type (all|channel)
- scope_id (null or channel_id)
- alerts_count
- wins_count
- losses_count
- pushes_count
- win_rate_pct
- total_pnl_usdc
- avg_pnl_usdc
- updated_at

## WR definitions
- WR = wins / resolved alerts
- resolved alerts = wins + losses
- pushes excluded from WR denominator unless you want a separate policy flag

## P/L definitions
- Total P/L = sum(profit_loss_usdc) - sum(fees_usdc)
- If profit_loss_usdc already includes fees, set fees_usdc to 0 and keep the formula consistent

## Period windows
- Total: all history
- Annual: rolling 365 days
- Quarterly: rolling 90 days
- Monthly: rolling 30 days

## Suggested views
- v_alert_stats_total
- v_alert_stats_year
- v_alert_stats_quarter
- v_alert_stats_month
- v_channel_stats_total
- v_channel_stats_year
- v_channel_stats_quarter
- v_channel_stats_month

## LOCUS compatibility
Export these artifacts alongside the vault:
- alerts.jsonl
- channels.json
- rollups.json
- schema.sql
- README.md

If LOCUS wants structured knowledge objects, map:
- alert → event
- channel → source/route
- rollup → metric summary

## Vault layout
- vaults/ompa/schema.sql
- vaults/ompa/alerts.jsonl
- vaults/ompa/rollups.json
- vaults/ompa/channels.json
- vaults/ompa/README.md

## Implementation note
WhaleTrax already has a wallet tracker schema and leaderboard code. This new vault should extend that pattern for alert/card analytics instead of replacing the existing wallet tables.
