"""
Rich display helpers for LockIns results.
"""

from __future__ import annotations

from typing import Optional

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .wallet_scanner import _safe_float

console = Console()


def _fmt_pct(v: float) -> str:
    return f"{v:.1f}%"


def _fmt_usdc(v: float) -> str:
    if abs(v) >= 1_000_000:
        return f"${v / 1_000_000:.2f}M"
    if abs(v) >= 1_000:
        return f"${v / 1_000:.1f}K"
    return f"${v:.2f}"


def _profit_style(v: float) -> str:
    if v > 0:
        return "green"
    if v < 0:
        return "red"
    return "white"


def _truncate_wallet(addr: str, max_len: int = 12) -> str:
    if len(addr) <= max_len:
        return addr
    return addr[:max_len] + "…"


# ── Tier labels ────────────────────────────────────────────────────────────────

TIER_LABELS = {
    "overall": "🏆 Overall",
    "penny": "🪙 Penny LockIns",
    "nickel": "🪙 Nickel LockIns",
}


# ── Main table ────────────────────────────────────────────────────────────────

def show_lockins_table(
    results: list,
    tier: str,
    title: Optional[str] = None,
    top_n: Optional[int] = None,
    scrubbed: bool = False,
) -> None:
    if top_n:
        results = results[:top_n]
    if not results:
        console.print(Panel("[yellow]No results found for this tier.[/yellow]"))
        return

    tier_label = TIER_LABELS.get(tier, tier.upper())
    default_title = f"{tier_label} — Top {len(results)} Wallets"
    table_title = title or default_title

    table = Table(
        title=table_title,
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        border_style="yellow",
        expand=False,
    )
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Wallet / Name", style="white", min_width=18)
    table.add_column("Trades", justify="right", width=7)
    table.add_column("W/L", justify="right", width=7)
    table.add_column("Win Rate", justify="right", width=9)
    table.add_column("Avg Price", justify="right", width=9)
    table.add_column("Bucket PnL", justify="right", min_width=11)
    table.add_column("Total PnL", justify="right", min_width=11)

    for idx, r in enumerate(results, start=1):
        label = r.display_name if r.display_name else _truncate_wallet(r.wallet)
        if scrubbed:
            label = _truncate_wallet(r.wallet, 10)

        # Bucket PnL = total_pnl (PnL within that bucket)
        # Total PnL = total_profit_usdc (leaderboard-level for overall, bucket PnL for penny/nickel)
        bucket_pnl = r.total_pnl
        total_pnl = r.total_profit_usdc if r.total_profit_usdc else r.total_pnl

        table.add_row(
            str(idx),
            label,
            str(r.total_trades),
            r.win_loss_str,
            _fmt_pct(r.win_rate_pct),
            f"{r.avg_price * 100:.0f}¢" if r.avg_price else "—",
            Text(_fmt_usdc(bucket_pnl), style=_profit_style(bucket_pnl)),
            Text(_fmt_usdc(total_pnl), style=_profit_style(total_pnl)),
        )

    console.print(table)


def show_run_state(state: dict) -> None:
    """Print last-run timestamps for all tiers."""
    rows = []
    for tier in ["overall", "penny", "nickel"]:
        info = state.get(tier, {})
        ts = info.get("last_run_ts", 0)
        iso = info.get("last_run_iso", "—")
        if ts > 0:
            from datetime import datetime, timezone
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        else:
            dt = "Never"
        rows.append((tier, dt, iso))

    table = Table(
        title="🔄 LockIns Run State",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        border_style="blue",
        expand=False,
    )
    table.add_column("Tier", style="white", min_width=16)
    table.add_column("Last Run", style="dim", min_width=22)
    table.add_column("ISO", style="dim", min_width=30)

    for tier, dt, iso in rows:
        label = TIER_LABELS.get(tier, tier.upper())
        table.add_row(label, dt, iso)

    console.print(table)


def show_wallet_lockins_profile(results: dict) -> None:
    """Show a single wallet's profile across all three tiers."""
    penny = results.get("penny")
    nickel = results.get("nickel")
    overall = results.get("overall")

    if not any([penny, nickel, overall]):
        console.print(Panel("[yellow]No LockIns data found for this wallet.[/yellow]"))
        return

    wallet_addr = (
        (penny or nickel or overall).wallet
        if any([penny, nickel, overall])
        else "Unknown"
    )
    name = (
        (penny or nickel or overall).display_name
        if any([penny, nickel, overall])
        else ""
    )

    title = f"🎯 LockIns Profile — {name or wallet_addr[:14]}…"
    lines = [f"[dim]Wallet:[/dim] {wallet_addr}", ""]

    for tier_label, stats in [
        ("🪙 Penny LockIns (90¢–99¢)", penny),
        ("🪙 Nickel LockIns (75¢–89¢)", nickel),
        ("🏆 Overall", overall),
    ]:
        if stats:
            lines.append(f"[bold]{tier_label}[/bold]")
            lines.append(
                f"  Trades: {stats.total_trades} | "
                f"W/L: {stats.win_loss_str} | "
                f"Win Rate: {_fmt_pct(stats.win_rate_pct)}"
            )
            lines.append(
                f"  Avg Price: {stats.avg_price * 100:.0f}¢ | "
                f"Bucket PnL: {_fmt_usdc(stats.total_pnl)}"
            )
            lines.append(
                f"  Total PnL: {_fmt_usdc(stats.total_profit_usdc or stats.total_pnl)} | "
                f"Biggest Win: {_fmt_usdc(stats.biggest_win)}"
            )
            lines.append("")
        else:
            lines.append(f"[bold]{tier_label}[/bold]")
            lines.append("  [dim]No data[/dim]")
            lines.append("")

    console.print(Panel("\n".join(lines), title=title, border_style="yellow", expand=False))
