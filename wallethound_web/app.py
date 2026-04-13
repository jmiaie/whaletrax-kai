"""
WalletHound web dashboard — Flask application.

Provides:
  • Dashboard page  — overview of all tracked wallets
  • Big Winners page
  • Consistent Winners page
  • Compounders page
  • Wallet detail page
  • REST API endpoints for AJAX/JSON consumers
"""

from __future__ import annotations

import logging
import os
import sys

from flask import Flask, jsonify, render_template, request

# Ensure the project root is importable
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src import config
from src.wallethound import scanner as wh_scanner
from src.wallethound import consistent_winners as cw
from src.wallethound import compounders as comp
from src.wallethound.models import WalletTier
from src.big_win_detector import scan_big_wins_for_wallet
from src.wallet_scanner import _parse_leaderboard_entry
from src import polymarket_client as pm

logging.basicConfig(level=logging.WARNING)

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), "templates"),
    static_folder=os.path.join(os.path.dirname(__file__), "static"),
)
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "wallethound-dev-key")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_top_n() -> int:
    """Read the ``top`` query parameter (default 20, max 100)."""
    try:
        n = int(request.args.get("top", 20))
    except (TypeError, ValueError):
        n = 20
    return max(1, min(n, 100))


def _hound_result_to_dict(r) -> dict:
    return {
        "wallet": r.wallet,
        "display_name": r.display_name,
        "tiers": [t.value for t in r.tiers],
        "tier_labels": r.tier_labels,
        "total_profit_usdc": round(r.total_profit_usdc, 2),
        "total_volume_usdc": round(r.total_volume_usdc, 2),
        "total_trades": r.total_trades,
        "win_rate_pct": round(r.win_rate_pct, 1),
        "biggest_win_usdc": round(r.biggest_win_usdc, 2),
        "big_win_count": r.big_win_count,
        "consistency_score": round(r.consistency_score, 1),
        "longest_win_streak": r.longest_win_streak,
        "profit_factor": round(r.profit_factor, 2),
        "organic_growth_pct": round(r.organic_growth_pct, 2),
        "organic_growth_usdc": round(r.organic_growth_usdc, 2),
        "compounding_score": round(r.compounding_score, 1),
        "total_deposits_usdc": round(r.total_deposits_usdc, 2),
        "total_withdrawals_usdc": round(r.total_withdrawals_usdc, 2),
    }


def _consistency_to_dict(s) -> dict:
    return {
        "wallet": s.wallet,
        "display_name": s.display_name,
        "consistency_score": round(s.consistency_score, 1),
        "win_rate_pct": round(s.win_rate_pct, 1),
        "total_resolved_trades": s.total_resolved_trades,
        "longest_win_streak": s.longest_win_streak,
        "profit_factor": round(s.profit_factor, 2),
        "avg_win_usdc": round(s.avg_win_usdc, 2),
        "avg_loss_usdc": round(s.avg_loss_usdc, 2),
        "total_profit_usdc": round(s.total_profit_usdc, 2),
    }


def _growth_to_dict(m) -> dict:
    return {
        "wallet": m.wallet,
        "display_name": m.display_name,
        "compounding_score": round(m.compounding_score, 1),
        "organic_growth_pct": round(m.organic_growth_pct, 2),
        "organic_growth_usdc": round(m.organic_growth_usdc, 2),
        "total_deposits_usdc": round(m.total_deposits_usdc, 2),
        "total_withdrawals_usdc": round(m.total_withdrawals_usdc, 2),
        "total_profit_usdc": round(m.total_profit_usdc, 2),
        "num_winning_periods": m.num_winning_periods,
        "num_periods": m.num_periods,
    }


# ── HTML Pages ───────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Dashboard landing page."""
    return render_template("index.html")


@app.route("/big-winners")
def big_winners_page():
    return render_template("big_winners.html")


@app.route("/consistent-winners")
def consistent_winners_page():
    return render_template("consistent_winners.html")


@app.route("/compounders")
def compounders_page():
    return render_template("compounders.html")


@app.route("/wallet/<wallet_address>")
def wallet_detail_page(wallet_address: str):
    return render_template("wallet_detail.html", wallet=wallet_address)


# ── REST API ─────────────────────────────────────────────────────────────────

@app.route("/api/hound/scan")
def api_hound_scan():
    """Scan the leaderboard and return all WalletHound results."""
    top_n = _get_top_n()
    tier = request.args.get("tier")
    tier_filter = WalletTier(tier) if tier else None
    results = wh_scanner.hound_leaderboard(top_n=top_n, tier_filter=tier_filter)
    return jsonify([_hound_result_to_dict(r) for r in results])


@app.route("/api/hound/wallet/<wallet_address>")
def api_hound_wallet(wallet_address: str):
    """WalletHound analysis for a single wallet."""
    result = wh_scanner.hound_wallet(wallet_address)
    return jsonify(_hound_result_to_dict(result))


@app.route("/api/consistent-winners")
def api_consistent_winners():
    """Scan the leaderboard for consistent winners."""
    top_n = _get_top_n()
    min_score = float(request.args.get("min_score", 50.0))
    raw_entries = pm.get_leaderboard(limit=top_n)
    scores = []
    for idx, raw in enumerate(raw_entries[:top_n], start=1):
        entry = _parse_leaderboard_entry(raw, rank=idx)
        if not entry.proxy_wallet:
            continue
        s = cw.score_wallet(entry.proxy_wallet, entry.name)
        if cw.qualifies_as_consistent(s, min_score=min_score):
            scores.append(s)
    scores.sort(key=lambda s: s.consistency_score, reverse=True)
    return jsonify([_consistency_to_dict(s) for s in scores])


@app.route("/api/compounders")
def api_compounders():
    """Scan the leaderboard for compounders."""
    top_n = _get_top_n()
    min_score = float(request.args.get("min_score", 40.0))
    min_growth = float(request.args.get("min_growth", 10.0))
    raw_entries = pm.get_leaderboard(limit=top_n)
    metrics_list = []
    for idx, raw in enumerate(raw_entries[:top_n], start=1):
        entry = _parse_leaderboard_entry(raw, rank=idx)
        if not entry.proxy_wallet:
            continue
        m = comp.analyse_wallet(entry.proxy_wallet, entry.name)
        if comp.qualifies_as_compounder(m, min_score=min_score, min_growth_pct=min_growth):
            metrics_list.append(m)
    metrics_list.sort(key=lambda m: m.compounding_score, reverse=True)
    return jsonify([_growth_to_dict(m) for m in metrics_list])


@app.route("/api/big-winners")
def api_big_winners():
    """Scan the leaderboard for big winners."""
    from src.big_win_detector import scan_big_wins_from_leaderboard
    top_n = _get_top_n()
    big_wins = scan_big_wins_from_leaderboard(top_n=top_n)
    return jsonify([
        {
            "wallet": bw.wallet,
            "display_name": bw.display_name,
            "market_question": bw.market_question,
            "outcome": bw.outcome,
            "profit_usdc": round(bw.profit_usdc, 2),
            "roi_pct": round(bw.roi_pct, 1),
            "trade_size_usdc": round(bw.trade_size_usdc, 2),
            "timestamp": bw.timestamp,
        }
        for bw in big_wins
    ])


# ── Run ──────────────────────────────────────────────────────────────────────

def create_app() -> Flask:
    """Application factory for external runners (gunicorn, etc.)."""
    return app


if __name__ == "__main__":
    port = int(os.getenv("WALLETHOUND_PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
