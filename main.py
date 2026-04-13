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
            raw_entries = pm.get_leaderboard(limit=top)
            for idx, (wallet_stats, raw) in enumerate(zip(wallets, raw_entries), start=1):
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
        market_big_wins: list = []
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


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cli()
