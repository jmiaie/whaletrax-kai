"""
Shared formatting and utility functions for WhaleTrax.
"""

from __future__ import annotations
import datetime


def fmt_usdc(val: float) -> str:
    """Format a USDC value with commas and 2 decimal places."""
    sign = "+" if val > 0 else ""
    return f"{sign}${val:,.2f}"


def fmt_pct(val: float) -> str:
    """Format a percentage value with 1 decimal place."""
    sign = "+" if val > 0 else ""
    return f"{sign}{val:.1f}%"


def fmt_ts(ts: int) -> str:
    """Format a unix timestamp into a UTC string."""
    if ts <= 0:
        return "—"
    try:
        return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).strftime(
            "%Y-%m-%d %H:%M UTC"
        )
    except (OSError, OverflowError, ValueError):
        return str(ts)


def profit_style(val: float) -> str:
    """Return the Rich style for a profit value."""
    if val > 0:
        return "bold green"
    if val < 0:
        return "bold red"
    return "dim"
