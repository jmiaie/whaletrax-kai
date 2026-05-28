"""
Rich terminal display helpers for WalletHound results.
"""

from __future__ import annotations

from typing import Optional

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..display import fmt_pct as _fmt_pct, fmt_usdc as _fmt_usdc, profit_style as _profit_style, console, WALLET_TRUNCATE_LEN
from ..models import WalletStats
from ..models import ConsistencyScore, GrowthMetrics, HoundResult, WalletTier


# ── Hound results table ──────────────────────────────────────────────────────

def show_hound_results(
    results: list[HoundResult],
    title: str = "🐕  WalletHound — Tracked Wallets",
    top_n: Optional[int] = None,
) -> None:
    """Print the main WalletHound results table."""
    if top_n:
        results = results[:top_n]

    if not results:
        console.print(Panel("[yellow]No wallets matched the WalletHound criteria.[/yellow]"))
        return

    table = Table(
        title=title,
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        border_style="yellow",
        expand=False,
    )
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Wallet / Name", style="white", min_width=18)
    table.add_column("Tiers", min_width=20, no_wrap=False)
    table.add_column("Profit", justify="right", min_width=12)
    table.add_column("Win Rate", justify="right", width=9)
    table.add_column("Consistency", justify="right", width=12)
    table.add_column("Organic Growth", justify="right", min_width=14)
    table.add_column("Deposits", justify="right", width=12)
    table.add_column("Big Wins", justify="right", width=9)

    for idx, r in enumerate(results, start=1):
        label = r.display_name if r.display_name else r.wallet[:WALLET_TRUNCATE_LEN] + "…"
        table.add_row(
            str(idx),
            label,
            r.tier_labels,
            Text(_fmt_usdc(r.total_profit_usdc), style=_profit_style(r.total_profit_usdc)),
            _fmt_pct(r.win_rate_pct) if r.win_rate_pct else "—",
            f"{r.consistency_score:.1f}" if r.consistency_score else "—",
            Text(_fmt_pct(r.organic_growth_pct), style=_profit_style(r.organic_growth_pct)),
            f"${r.total_deposits_usdc:,.0f}" if r.total_deposits_usdc else "—",
            str(r.big_win_count) if r.big_win_count else "—",
        )

    console.print(table)


# ── Consistency detail table ─────────────────────────────────────────────────

def show_consistency_detail(scores: list[ConsistencyScore], title: str = "🎯  Consistent Winners") -> None:
    """Print a table of consistency-scored wallets."""
    if not scores:
        console.print(Panel("[yellow]No consistent winners found.[/yellow]"))
        return

    table = Table(
        title=title,
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        border_style="green",
        expand=False,
    )
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Wallet / Name", style="white", min_width=18)
    table.add_column("Score", justify="right", width=8)
    table.add_column("Win Rate", justify="right", width=9)
    table.add_column("Trades", justify="right", width=8)
    table.add_column("Win Streak", justify="right", width=11)
    table.add_column("Profit Factor", justify="right", width=13)
    table.add_column("Avg Win", justify="right", width=11)
    table.add_column("Avg Loss", justify="right", width=11)
    table.add_column("Profit", justify="right", min_width=12)

    for idx, s in enumerate(scores, start=1):
        label = s.display_name if s.display_name else s.wallet[:WALLET_TRUNCATE_LEN] + "…"
        table.add_row(
            str(idx),
            label,
            f"{s.consistency_score:.1f}",
            _fmt_pct(s.win_rate_pct),
            str(s.total_resolved_trades),
            str(s.longest_win_streak),
            f"{s.profit_factor:.2f}",
            f"${s.avg_win_usdc:,.2f}",
            f"${s.avg_loss_usdc:,.2f}",
            Text(_fmt_usdc(s.total_profit_usdc), style=_profit_style(s.total_profit_usdc)),
        )

    console.print(table)


# ── Compounder detail table ──────────────────────────────────────────────────

def show_compounder_detail(metrics_list: list[GrowthMetrics], title: str = "📈  Compounders") -> None:
    """Print a table of compounder-scored wallets."""
    if not metrics_list:
        console.print(Panel("[yellow]No compounders found.[/yellow]"))
        return

    table = Table(
        title=title,
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        border_style="magenta",
        expand=False,
    )
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Wallet / Name", style="white", min_width=18)
    table.add_column("Score", justify="right", width=8)
    table.add_column("Organic Growth", justify="right", min_width=14)
    table.add_column("Organic $", justify="right", min_width=12)
    table.add_column("Deposits", justify="right", width=12)
    table.add_column("Withdrawals", justify="right", width=12)
    table.add_column("Win Periods", justify="right", width=12)
    table.add_column("Total Profit", justify="right", min_width=12)

    for idx, m in enumerate(metrics_list, start=1):
        label = m.display_name if m.display_name else m.wallet[:WALLET_TRUNCATE_LEN] + "…"
        table.add_row(
            str(idx),
            label,
            f"{m.compounding_score:.1f}",
            Text(_fmt_pct(m.organic_growth_pct), style=_profit_style(m.organic_growth_pct)),
            Text(_fmt_usdc(m.organic_growth_usdc), style=_profit_style(m.organic_growth_usdc)),
            f"${m.total_deposits_usdc:,.0f}",
            f"${m.total_withdrawals_usdc:,.0f}",
            f"{m.num_winning_periods}/{m.num_periods}",
            Text(_fmt_usdc(m.total_profit_usdc), style=_profit_style(m.total_profit_usdc)),
        )

    console.print(table)


# ── Single wallet hound detail panel ─────────────────────────────────────────

def show_hound_wallet_detail(result: HoundResult) -> None:
    """Print a detailed WalletHound panel for a single wallet."""
    name = result.display_name or result.wallet
    title = f"🐕  WalletHound Analysis — [bold cyan]{name}[/bold cyan]"

    lines = [
        f"[dim]Address:[/dim]            {result.wallet}",
        f"[dim]Tiers:[/dim]              {result.tier_labels}",
        "",
        "[bold]── Trading Performance ──[/bold]",
        f"[dim]Total Profit:[/dim]       {Text(_fmt_usdc(result.total_profit_usdc), style=_profit_style(result.total_profit_usdc))}",
        f"[dim]Total Volume:[/dim]       ${result.total_volume_usdc:,.2f}",
        f"[dim]Trades:[/dim]             {result.total_trades}",
        f"[dim]Win Rate:[/dim]           {_fmt_pct(result.win_rate_pct)}",
        f"[dim]Big Wins:[/dim]           {result.big_win_count}",
        f"[dim]Biggest Win:[/dim]        [green]{_fmt_usdc(result.biggest_win_usdc)}[/green]",
        "",
        "[bold]── Consistency ──[/bold]",
        f"[dim]Consistency Score:[/dim]  {result.consistency_score:.1f}/100",
        f"[dim]Longest Win Streak:[/dim] {result.longest_win_streak}",
        f"[dim]Profit Factor:[/dim]      {result.profit_factor:.2f}",
        "",
        "[bold]── Balance Growth ──[/bold]",
        f"[dim]Organic Growth:[/dim]     {Text(_fmt_pct(result.organic_growth_pct), style=_profit_style(result.organic_growth_pct))}",
        f"[dim]Organic Growth $:[/dim]   {Text(_fmt_usdc(result.organic_growth_usdc), style=_profit_style(result.organic_growth_usdc))}",
        f"[dim]Compounding Score:[/dim]  {result.compounding_score:.1f}/100",
        f"[dim]Total Deposits:[/dim]     ${result.total_deposits_usdc:,.2f}",
        f"[dim]Total Withdrawals:[/dim]  ${result.total_withdrawals_usdc:,.2f}",
    ]

    console.print(Panel("\n".join(lines), title=title, border_style="yellow", expand=False))
