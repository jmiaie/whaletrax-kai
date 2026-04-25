"""
Rich terminal display helpers for WhaleTrax.
"""

from __future__ import annotations

import datetime
from typing import Any, Optional

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Consistent wallet address truncation length used throughout the display layer
WALLET_TRUNCATE_LEN = 12

from .models import BigWin, WalletStats
from .utils import fmt_usdc, fmt_pct, fmt_ts, profit_style

console = Console()


# ── Leaderboard table ─────────────────────────────────────────────────────────

def show_leaderboard(wallets: list[WalletStats], top_n: Optional[int] = None) -> None:
    """Print a ranked leaderboard table."""
    if top_n:
        wallets = wallets[:top_n]

    table = Table(
        title="🐋  WhaleTrax — Polymarket Leaderboard",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        border_style="blue",
        expand=False,
    )
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Wallet / Name", style="white", min_width=20)
    table.add_column("Profit (USDC)", justify="right", min_width=14)
    table.add_column("Volume (USDC)", justify="right", min_width=14)
    table.add_column("Trades", justify="right", width=8)
    table.add_column("Win Rate", justify="right", width=9)
    table.add_column("Net ROI", justify="right", width=9)
    table.add_column("Big Wins", justify="right", width=9)

    for w in wallets:
        label = w.display_name if w.display_name else w.wallet[:WALLET_TRUNCATE_LEN] + "…"
        table.add_row(
            str(w.rank or "—"),
            label,
            Text(fmt_usdc(w.total_profit_usdc), style=profit_style(w.total_profit_usdc)),
            f"${w.total_volume_usdc:,.0f}",
            str(w.total_trades),
            fmt_pct(w.win_rate_pct) if w.win_rate_pct else "—",
            Text(fmt_pct(w.net_roi_pct), style=profit_style(w.net_roi_pct)),
            str(w.big_win_count) if w.big_win_count else "—",
        )

    console.print(table)


# ── Wallet detail panel ────────────────────────────────────────────────────────

def show_wallet_detail(stats: WalletStats) -> None:
    """Print a detailed panel for a single wallet."""
    name = stats.display_name or stats.wallet
    title = f"🔍  Wallet Analysis — [bold cyan]{name}[/bold cyan]"

    lines = [
        f"[dim]Address:[/dim]        {stats.wallet}",
        f"[dim]Total Profit:[/dim]   {Text(fmt_usdc(stats.total_profit_usdc), style=profit_style(stats.total_profit_usdc))}",
        f"[dim]Total Volume:[/dim]   ${stats.total_volume_usdc:,.2f}",
        f"[dim]Net ROI:[/dim]        {Text(fmt_pct(stats.net_roi_pct), style=profit_style(stats.net_roi_pct))}",
        f"[dim]Trades:[/dim]         {stats.total_trades}",
        f"[dim]Wins / Losses:[/dim]  {stats.winning_trades} / {stats.losing_trades}",
        f"[dim]Win Rate:[/dim]       {fmt_pct(stats.win_rate_pct)}",
        f"[dim]Avg Trade ROI:[/dim]  {fmt_pct(stats.avg_roi_pct)}",
        f"[dim]Biggest Win:[/dim]    [green]{fmt_usdc(stats.biggest_win_usdc)}[/green]",
        f"[dim]Biggest Loss:[/dim]   [red]{fmt_usdc(stats.biggest_loss_usdc)}[/red]",
        f"[dim]Big Wins:[/dim]       {stats.big_win_count}",
    ]

    console.print(Panel("\n".join(lines), title=title, border_style="blue", expand=False))


# ── Big-wins table ─────────────────────────────────────────────────────────────

def show_big_wins(big_wins: list[BigWin], title: str = "💰  Big Wins") -> None:
    """Print a table of big-win trades."""
    if not big_wins:
        console.print(Panel("[yellow]No big wins found with current thresholds.[/yellow]"))
        return

    table = Table(
        title=title,
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        border_style="green",
        expand=False,
    )
    table.add_column("Wallet / Name", style="white", min_width=18)
    table.add_column("Market", style="dim", min_width=30, max_width=50, no_wrap=False)
    table.add_column("Outcome", style="white", width=8)
    table.add_column("Cost (USDC)", justify="right", width=12)
    table.add_column("Profit (USDC)", justify="right", width=14)
    table.add_column("ROI", justify="right", width=9)
    table.add_column("Date", justify="right", width=20)

    for bw in big_wins:
        label = bw.display_name if bw.display_name else bw.wallet[:WALLET_TRUNCATE_LEN] + "…"
        table.add_row(
            label,
            bw.market_question or bw.market_id or "—",
            bw.outcome or "—",
            f"${bw.trade_size_usdc:,.2f}",
            Text(fmt_usdc(bw.profit_usdc), style="bold green"),
            Text(fmt_pct(bw.roi_pct), style="bold green"),
            fmt_ts(bw.timestamp),
        )

    console.print(table)


# ── Market holders table ───────────────────────────────────────────────────────

def show_market_holders(holders: list[dict[str, Any]], market_question: str = "") -> None:
    """Print top holders for a market."""
    title = f"🏦  Top Holders — {market_question}" if market_question else "🏦  Top Holders"
    table = Table(title=title, box=box.ROUNDED, header_style="bold cyan", border_style="magenta")
    table.add_column("#", width=4, justify="right")
    table.add_column("Wallet / Name", min_width=20)
    table.add_column("Outcome", width=8)
    table.add_column("Shares", justify="right", width=12)
    table.add_column("Value (USDC)", justify="right", width=14)

    for idx, h in enumerate(holders, start=1):
        name = str(h.get("name") or h.get("displayName") or "")
        wallet = str(
            h.get("proxyWallet") or h.get("proxy_wallet") or h.get("address") or h.get("user") or ""
        )
        label = name or (wallet[:14] + "…" if wallet else "—")
        outcome = str(h.get("outcome") or h.get("outcomeIndex") or "—")
        shares = float(h.get("size") or h.get("shares") or 0)
        value = float(h.get("value") or h.get("currentValue") or 0)
        table.add_row(
            str(idx),
            label,
            outcome,
            f"{shares:,.2f}",
            f"${value:,.2f}",
        )

    console.print(table)


# ── Generic info ───────────────────────────────────────────────────────────────

def print_info(msg: str) -> None:
    console.print(f"[cyan]ℹ[/cyan]  {msg}")


def print_success(msg: str) -> None:
    console.print(f"[green]✔[/green]  {msg}")


def print_warning(msg: str) -> None:
    console.print(f"[yellow]⚠[/yellow]  {msg}")


def print_error(msg: str) -> None:
    console.print(f"[bold red]✖[/bold red]  {msg}")
