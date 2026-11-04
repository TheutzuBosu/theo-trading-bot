"""Post-mortem trade autopsy and lesson generator in simple Romanian (Faza B, B4).

Classifies each closed trade mechanically and generates a 1-sentence lesson in Romanian
(via Gemini Flash-Lite if available, or a deterministic fallback so offline/paper execution
never fails if the AI API is unreachable).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.config import settings


def classify_trade_outcome(trade: Mapping[str, Any]) -> str:
    """Classify a closed trade into a deterministic post-mortem category."""
    pnl = float(trade.get("pnl", 0.0) or 0.0)
    r_mult = float(trade.get("r_multiple", 0.0) or 0.0)
    exit_reason = str(trade.get("exit_reason", "")).lower()
    mfe_r = float(trade.get("mfe_r", 0.0) or 0.0)
    partial = bool(trade.get("partial_exit", False))

    if pnl > 0 or r_mult > 0:
        if partial or exit_reason == "target":
            return "win_target"
        return "win_trend_eod"
    if exit_reason == "stop":
        if mfe_r >= 0.5:
            return "loss_reversal_after_gain"
        return "loss_false_breakout"
    return "loss_time_decay"


def _mechanical_lesson(trade: Mapping[str, Any]) -> str:
    symbol = str(trade.get("symbol", "SPY"))
    direction = str(trade.get("direction", "long"))
    pnl = float(trade.get("pnl", 0.0) or 0.0)
    r_mult = float(trade.get("r_multiple", 0.0) or 0.0)
    exit_reason = str(trade.get("exit_reason", "eod")).lower()
    mfe_r = float(trade.get("mfe_r", 0.0) or 0.0)

    if pnl > 0:
        if exit_reason == "target" or bool(trade.get("partial_exit", False)):
            return (
                f"Tranzacție {direction} pe {symbol} închisă pe plus "
                f"({pnl:+.2f} $, {r_mult:+.2f}R): "
                f"ținta de profit a fost atinsă și stop-ul urcat la VWAP a protejat câștigul."
            )
        return (
            f"Tranzacție {direction} pe {symbol} câștigătoare ({pnl:+.2f} $, {r_mult:+.2f}R): "
            f"spargerea benzii de zgomot s-a menținut până la ieșirea programată ({exit_reason})."
        )

    if exit_reason == "stop":
        if mfe_r >= 0.5:
            return (
                f"Poziția {direction} pe {symbol} a mers inițial în direcția bună "
                f"(+{mfe_r:.2f}R), dar s-a întors sub stop ({pnl:+.2f} $, {r_mult:+.2f}R); "
                f"pierderea a rămas sub control."
            )
        return (
            f"Spargere falsă pe {symbol} ({direction}): prețul a revenit rapid în banda de zgomot "
            f"și stop-ul a limitat pierderea la {pnl:+.2f} $ ({r_mult:+.2f}R)."
        )

    return (
        f"Poziția {direction} pe {symbol} s-a închis la {exit_reason} cu {pnl:+.2f} $ "
        f"({r_mult:+.2f}R) fără continuare suficientă a trendului."
    )


def generate_trade_lesson(trade: Mapping[str, Any], client: Any = None) -> str:
    """Return a concise 1-sentence lesson in Romanian for the closed trade."""
    fallback = _mechanical_lesson(trade)
    if client is None:
        return fallback

    prompt = (
        "Ești analistul post-mortem al unui bot de day trading. Explică în cel mult 1 frază "
        "scurtă, în română simplă, ce s-a întâmplat la această tranzacție și ce reținem:\n"
        f"Simbol: {trade.get('symbol')}, Direcție: {trade.get('direction')}, "
        f"PnL: {trade.get('pnl')} $, R: {trade.get('r_multiple')}R, "
        f"Motiv intrare: {trade.get('entry_reason')}, Motiv ieșire: {trade.get('exit_reason')}, "
        f"MFE: {trade.get('mfe_r')}R, MAE: {trade.get('mae_r')}R."
    )
    try:
        resp = client.models.generate_content(model=settings.GEMINI_MODEL, contents=prompt)
        text = (getattr(resp, "text", None) or "").strip()
        return text if text else fallback
    except Exception:
        return fallback


def build_autopsy_record(trade: Mapping[str, Any], client: Any = None) -> dict[str, Any]:
    """Build a JSON-serializable autopsy record for `state/autopsies.jsonl`."""
    return {
        "symbol": str(trade.get("symbol", "")),
        "direction": str(trade.get("direction", "")),
        "entry_time": str(trade.get("entry_time", "")),
        "exit_time": str(trade.get("exit_time", "")),
        "pnl": float(trade.get("pnl", 0.0) or 0.0),
        "r_multiple": float(trade.get("r_multiple", 0.0) or 0.0),
        "mae_r": float(trade.get("mae_r", 0.0) or 0.0),
        "mfe_r": float(trade.get("mfe_r", 0.0) or 0.0),
        "exit_reason": str(trade.get("exit_reason", "")),
        "entry_reason": str(trade.get("entry_reason", "")),
        "category": classify_trade_outcome(trade),
        "lesson": generate_trade_lesson(trade, client=client),
    }


__all__ = [
    "build_autopsy_record",
    "classify_trade_outcome",
    "generate_trade_lesson",
]
