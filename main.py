#!/usr/bin/env python3
"""
WhaleTrax – Polymarket Blockchain Wallet & Big-Win Scanner

Usage:
  python main.py scan-leaderboard [--top N]
  python main.py scan-big-wins    [--top N]
  python main.py scan-wallet      <wallet_address>
  python main.py scan-market      <market_id_or_slug>

Run `python main.py --help` for full usage.
"""

import logging
import sys

import click
from rich.progress import Progress, SpinnerColumn, TextColumn

from src import config
from src import big_win_detector as bwd
from src import wallet_scanner as ws
from src import polymarket_client as pm
from src.display import (
    console,
    print_error,
    print_info,
    print_warning,
    show_big_wins,
    show_leaderboard,
    show_market_holders,
    show_wallet_detail,
)
from src.wallethound import scanner as wh_scanner
from src.models import WalletTier
from src.wallethound.display import (
    show_hound_results,
    show_hound_wallet_detail,
    show_consistency_detail,
    show_compounder_detail,
)
from src.wallethound import consistent_winners as cw
from src.wallethound import compounders as comp

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s %(name)s: %(message)s",
)


# ── CLI root ──────────────────────────────────────────────────────────────────

@click.group()
@click.version_option(version="1.0.0", prog_name="whaletrax")
def cli() -> None:
    """WhaleTrax — identify highly profitable Polymarket wallets, plays, and traders."""


# ── scan-leaderboard ──────────────────────────────────────────────────────────

@cli.command("scan-leaderboard")
@click.option(
    "--top",
    default=config.DISPLAY_TOP_N,
    show_default=True,
    help="Number of top wallets to display.",
    type=click.IntRange(1, 100),
)
@click.option(
    "--big-wins/--no-big-wins",
    default=True,
    show_default=True,
    help="Also fetch big-win counts for each wallet.",
)
def scan_leaderboard_cmd(top: int, big_wins: bool) -> None:
    """Show the top Polymarket traders ranked by profit."""
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
        console=console,
    ) as progress:
        task = progress.add_task("Fetching leaderboard …", total=None)
        wallets = ws.scan_leaderboard(top_n=top)
        if not wallets:
            print_warning("Leaderboard returned no data. Polymarket API may be unavailable.")
            sys.exit(1)

        if big_wins:
            progress.update(task, description="Scanning big wins …")
            for wallet_stats in wallets:
                entry_wins = bwd.scan_big_wins_for_wallet(
                    wallet_stats.wallet, wallet_stats.display_name
                )
                bwd.annotate_wallet_big_wins(wallet_stats, entry_wins)

    show_leaderboard(wallets, top_n=top)


# ── scan-big-wins ─────────────────────────────────────────────────────────────

@cli.command("scan-big-wins")
@click.option(
    "--top",
    default=config.LEADERBOARD_TOP_N,
    show_default=True,
    help="Number of top leaderboard wallets to scan.",
    type=click.IntRange(1, 100),
)
@click.option(
    "--min-profit",
    default=config.BIG_WIN_MIN_PROFIT_USDC,
    show_default=True,
    help="Minimum profit in USDC to qualify as a big win.",
    type=float,
)
@click.option(
    "--min-roi",
    default=config.BIG_WIN_MIN_ROI_PCT,
    show_default=True,
    help="Minimum ROI %% to qualify as a big win.",
    type=float,
)
@click.option(
    "--min-size",
    default=config.BIG_WIN_MIN_TRADE_SIZE_USDC,
    show_default=True,
    help="Minimum trade size in USDC to qualify.",
    type=float,
)
def scan_big_wins_cmd(top: int, min_profit: float, min_roi: float, min_size: float) -> None:
    """Find the largest single-trade wins across the top Polymarket traders."""
    # Apply per-invocation overrides to config at runtime
    config.BIG_WIN_MIN_PROFIT_USDC = min_profit
    config.BIG_WIN_MIN_ROI_PCT = min_roi
    config.BIG_WIN_MIN_TRADE_SIZE_USDC = min_size

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
        console=console,
    ) as progress:
        progress.add_task(f"Scanning big wins across top-{top} wallets …", total=None)
        big_wins = bwd.scan_big_wins_from_leaderboard(top_n=top)

    if not big_wins:
        print_warning(
            f"No big wins found with thresholds: "
            f"profit≥${min_profit:,.0f}, ROI≥{min_roi:.0f}%, size≥${min_size:,.0f}."
        )
        print_info("Try lowering thresholds with --min-profit / --min-roi / --min-size.")
        return

    show_big_wins(big_wins, title=f"💰  Big Wins (top-{top} wallets, profit≥${min_profit:,.0f})")
    print_info(f"Found {len(big_wins)} big win(s).")


# ── scan-wallet ───────────────────────────────────────────────────────────────

@cli.command("scan-wallet")
@click.argument("wallet")
@click.option(
    "--big-wins/--no-big-wins",
    default=True,
    show_default=True,
    help="Also show big-win trades for this wallet.",
)
def scan_wallet_cmd(wallet: str, big_wins: bool) -> None:
    """Deep-dive analysis of a single wallet address."""
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
        console=console,
    ) as progress:
        progress.add_task(f"Scanning wallet {wallet[:14]}…", total=None)
        stats = ws.scan_wallet(wallet)
        wallet_big_wins = []
        if big_wins:
            wallet_big_wins = bwd.scan_big_wins_for_wallet(wallet, stats.display_name)
            bwd.annotate_wallet_big_wins(stats, wallet_big_wins)

    show_wallet_detail(stats)
    if big_wins:
        show_big_wins(wallet_big_wins, title=f"💰  Big Wins — {stats.display_name or wallet[:16]}…")


# ── scan-market ───────────────────────────────────────────────────────────────

@cli.command("scan-market")
@click.argument("market_id")
@click.option(
    "--top-holders",
    default=config.MARKET_TOP_HOLDERS_N,
    show_default=True,
    help="Number of top holders to display.",
    type=click.IntRange(1, 100),
)
@click.option(
    "--big-wins/--no-big-wins",
    default=True,
    show_default=True,
    help="Also find big wins from top holders in this market.",
)
def scan_market_cmd(market_id: str, top_holders: int, big_wins: bool) -> None:
    """Analyse top holders and big wins for a specific Polymarket market."""
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
        console=console,
    ) as progress:
        progress.add_task(f"Fetching market {market_id} …", total=None)

        market_info = pm.get_market(market_id)
        question = ""
        if market_info:
            question = str(
                market_info.get("question")
                or market_info.get("title")
                or market_info.get("description")
                or ""
            )

        holders = pm.get_market_holders(market_id, limit=top_holders)
        market_big_wins: list[BigWin] = []
        if big_wins:
            market_big_wins = bwd.scan_big_wins_for_market(market_id, top_holders=top_holders)

    if not holders and not market_big_wins:
        print_warning(f"No data found for market '{market_id}'.")
        print_info("Check that the market ID is a valid Polymarket condition ID.")
        sys.exit(1)

    if holders:
        show_market_holders(holders, market_question=question or market_id)

    if big_wins:
        show_big_wins(
            market_big_wins,
            title=f"💰  Big Wins — {question or market_id}",
        )


@cli.command("backfill-wallet-profiles")
@click.option(
    "--top",
    default=config.LEADERBOARD_TOP_N,
    show_default=True,
    help="Number of top leaderboard wallets to backfill.",
    type=click.IntRange(1, 100),
)
def backfill_wallet_profiles_cmd(top: int) -> None:
    """Backfill wallet profiles from closed Polymarket positions and persist the profile vault."""
    from wallet_profiles import update_profile

    raw_entries = pm.get_leaderboard(limit=top)
    if not raw_entries:
        print_warning("Leaderboard returned no data.")
        sys.exit(1)

    total_wallets = 0
    total_closed = 0
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
        console=console,
    ) as progress:
        task = progress.add_task(f"Backfilling top-{top} wallets …", total=None)
        from src.parsers import parse_leaderboard_entry
        for idx, raw in enumerate(raw_entries[:top], start=1):
            entry = parse_leaderboard_entry(raw, rank=idx)
            if not entry.proxy_wallet:
                continue
            progress.update(task, description=f"Backfilling {entry.proxy_wallet[:14]}…")
            closed = pm.get_user_closed_positions(entry.proxy_wallet)
            if not closed:
                continue
            update_profile(entry.proxy_wallet, entry.name, closed)
            total_wallets += 1
            total_closed += len(closed)

    print_info(f"Backfill complete: {total_wallets} wallet(s), {total_closed} closed position(s) ingested.")


@cli.command("backfill-status")
def backfill_status_cmd() -> None:
    """Show resumable backfill progress for the wallet profile batches."""
    import json
    from pathlib import Path

    progress_file = Path('/tmp/whaletrax_backfill_progress.json')
    if not progress_file.exists():
        print_info("No backfill progress file found yet.")
        return

    data = json.loads(progress_file.read_text())
    print_info(
        f"Backfill status: {data.get('status', 'unknown')} | "
        f"start={data.get('start')} | count={data.get('count')} | "
        f"updated={data.get('updated_wallets', 0)} | closed={data.get('closed_positions', 0)}"
    )


# ── WalletHound commands ──────────────────────────────────────────────────────

@cli.group("wallethound")
def wallethound_group() -> None:
    """🐕  WalletHound — track big winners, consistent winners, and compounders."""


@wallethound_group.command("scan")
@click.option(
    "--top",
    default=config.LEADERBOARD_TOP_N,
    show_default=True,
    help="Number of top leaderboard wallets to scan.",
    type=click.IntRange(1, 100),
)
@click.option(
    "--tier",
    default=None,
    type=click.Choice(["big_winner", "consistent_winner", "compounder"], case_sensitive=False),
    help="Filter results to a specific tier.",
)
def wallethound_scan_cmd(top: int, tier: str | None) -> None:
    """Scan the leaderboard for big winners, consistent winners, and compounders."""
    tier_filter = WalletTier(tier) if tier else None

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
        console=console,
    ) as progress:
        progress.add_task(
            f"🐕 WalletHound scanning top-{top} wallets …", total=None,
        )
        results = wh_scanner.hound_leaderboard(top_n=top, tier_filter=tier_filter)

    if not results:
        print_warning("No wallets matched the WalletHound criteria.")
        return

    tier_label = tier_filter.value if tier_filter else "all tiers"
    show_hound_results(
        results,
        title=f"🐕  WalletHound — Top-{top} ({tier_label})",
    )
    print_info(f"Found {len(results)} wallet(s) matching criteria.")


@wallethound_group.command("wallet")
@click.argument("wallet")
def wallethound_wallet_cmd(wallet: str) -> None:
    """Deep-dive WalletHound analysis of a single wallet."""
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
        console=console,
    ) as progress:
        progress.add_task(f"🐕 Analyzing wallet {wallet[:14]}…", total=None)
        result = wh_scanner.hound_wallet(wallet)

    show_hound_wallet_detail(result)


@wallethound_group.command("consistent")
@click.option(
    "--top",
    default=config.LEADERBOARD_TOP_N,
    show_default=True,
    help="Number of top leaderboard wallets to scan.",
    type=click.IntRange(1, 100),
)
@click.option(
    "--min-score",
    default=50.0,
    show_default=True,
    help="Minimum consistency score (0–100) to qualify.",
    type=float,
)
def wallethound_consistent_cmd(top: int, min_score: float) -> None:
    """Find the most consistent winners on the leaderboard."""
    from src.wallethound.consistent_winners import score_wallet, qualifies_as_consistent
    from src.models import ConsistencyScore

    raw_entries = pm.get_leaderboard(limit=top)
    if not raw_entries:
        print_warning("Leaderboard returned no data.")
        return

    scores: list[ConsistencyScore] = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
        console=console,
    ) as progress:
        progress.add_task(f"🎯 Scoring consistency for top-{top} wallets …", total=None)
        from src.parsers import parse_leaderboard_entry
        for idx, raw in enumerate(raw_entries[:top], start=1):
            entry = parse_leaderboard_entry(raw, rank=idx)
            if not entry.proxy_wallet:
                continue
            s = score_wallet(entry.proxy_wallet, entry.name)
            if qualifies_as_consistent(s, min_score=min_score):
                scores.append(s)

    scores.sort(key=lambda s: s.consistency_score, reverse=True)
    show_consistency_detail(scores)
    print_info(f"Found {len(scores)} consistent winner(s) (score ≥ {min_score:.0f}).")


@wallethound_group.command("compounders")
@click.option(
    "--top",
    default=config.LEADERBOARD_TOP_N,
    show_default=True,
    help="Number of top leaderboard wallets to scan.",
    type=click.IntRange(1, 100),
)
@click.option(
    "--min-score",
    default=40.0,
    show_default=True,
    help="Minimum compounding score (0–100) to qualify.",
    type=float,
)
@click.option(
    "--min-growth",
    default=10.0,
    show_default=True,
    help="Minimum organic growth %% to qualify.",
    type=float,
)
def wallethound_compounders_cmd(top: int, min_score: float, min_growth: float) -> None:
    """Find wallets compounding their balances through wins (not deposits)."""
    from src.wallethound.compounders import analyse_wallet, qualifies_as_compounder
    from src.models import GrowthMetrics

    raw_entries = pm.get_leaderboard(limit=top)
    if not raw_entries:
        print_warning("Leaderboard returned no data.")
        return

    metrics_list: list[GrowthMetrics] = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
        console=console,
    ) as progress:
        progress.add_task(f"📈 Analyzing compounding for top-{top} wallets …", total=None)
        from src.parsers import parse_leaderboard_entry
        for idx, raw in enumerate(raw_entries[:top], start=1):
            entry = parse_leaderboard_entry(raw, rank=idx)
            if not entry.proxy_wallet:
                continue
            m = analyse_wallet(entry.proxy_wallet, entry.name)
            if qualifies_as_compounder(m, min_score=min_score, min_growth_pct=min_growth):
                metrics_list.append(m)

    metrics_list.sort(key=lambda m: m.compounding_score, reverse=True)
    show_compounder_detail(metrics_list)
    print_info(f"Found {len(metrics_list)} compounder(s) (score ≥ {min_score:.0f}, growth ≥ {min_growth:.0f}%).")


@wallethound_group.command("web")
@click.option(
    "--port",
    default=5000,
    show_default=True,
    help="Port to serve the web dashboard on.",
    type=int,
)
@click.option(
    "--debug/--no-debug",
    default=False,
    show_default=True,
    help="Run Flask in debug mode.",
)
def wallethound_web_cmd(port: int, debug: bool) -> None:
    """Start the WalletHound web dashboard."""
    from wallethound_web.app import app as flask_app

    print_info(f"Starting WalletHound web dashboard on http://localhost:{port}")
    flask_app.run(host="0.0.0.0", port=port, debug=debug)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cli()
