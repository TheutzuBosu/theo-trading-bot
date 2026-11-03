"""Offline tests for src/alerts/telegram.py (simulated HTTP)."""

from __future__ import annotations

from src.alerts.telegram import (
    fetch_chat_id,
    format_daily_loss_limit_message,
    format_daily_summary_message,
    format_entry_message,
    format_error_message,
    format_exit_message,
    format_kill_message,
    send_daily_loss_limit_alert,
    send_daily_summary_alert,
    send_entry_alert,
    send_error_alert,
    send_exit_alert,
    send_kill_alert,
    send_telegram_message,
)


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _FakeSession:
    def __init__(
        self, get_resp: _FakeResponse | None = None, post_resp: _FakeResponse | None = None
    ):
        self.get_resp = get_resp or _FakeResponse(200, {"ok": True, "result": []})
        self.post_resp = post_resp or _FakeResponse(200, {"ok": True, "result": {"message_id": 1}})
        self.gets: list[str] = []
        self.posts: list[tuple[str, dict]] = []

    def get(self, url: str, timeout: int = 10) -> _FakeResponse:
        self.gets.append(url)
        return self.get_resp

    def post(self, url: str, json: dict, timeout: int = 10) -> _FakeResponse:
        self.posts.append((url, json))
        return self.post_resp


def test_format_entry_message_romanian():
    msg = format_entry_message(
        symbol="SPY",
        direction="long",
        qty=0.86,
        entry_price=585.02,
        stop=582.10,
        risk_pct=0.005,
        reason="Prețul a ieșit deasupra benzii de zgomot de 14 zile la 10:00 ET.",
        strategy="D1",
    )
    assert "INTRARE [PAPER] — SPY" in msg
    assert "LONG (cumpărare) · Strategie: D1" in msg
    assert "0,86 acțiuni la 585,02 $" in msg
    assert "Stop-loss: 582,10 $ (risc 0,50% din capital)" in msg
    assert "De ce: Prețul a ieșit" in msg


def test_format_exit_message_win_and_loss():
    win_msg = format_exit_message(
        symbol="SPY",
        direction="long",
        pnl=2.64,
        r_multiple=1.05,
        exit_reason="eod",
        exit_price=588.09,
        lesson="Trend curat peste VWAP toată ziua.",
    )
    assert "✅ IEȘIRE [PAPER] — SPY (LONG) la 588,09 $" in win_msg
    assert "+2,64 $ (+1,05 R)" in win_msg
    assert "Închis automat la finalul sesiunii" in win_msg
    assert "Observație: Trend curat" in win_msg

    loss_msg = format_exit_message(
        symbol="QQQ",
        direction="long",
        pnl=-2.43,
        r_multiple=-1.01,
        exit_reason="stop",
    )
    assert "🔴 IEȘIRE [PAPER] — QQQ (LONG)" in loss_msg
    assert "−2,43 $ (−1,01 R)" in loss_msg
    assert "Oprit la pragul de protecție (stop-loss)" in loss_msg


def test_format_daily_summary_and_loss_limit():
    summary = format_daily_summary_message(
        date="2026-11-03",
        equity=510.12,
        daily_pnl=2.64,
        daily_pnl_pct=0.52,
        total_pnl=10.12,
        total_pnl_pct=2.02,
        trades_count=2,
        wins_count=1,
        drawdown_pct=-0.48,
    )
    assert "REZUMAT ZILNIC [PAPER] — 2026-11-03" in summary
    assert "510,12 $" in summary
    assert "+2,64 $ (+0,52%)" in summary
    assert "2 (1 câștigate, 1 pierdute)" in summary

    loss_alert = format_daily_loss_limit_message(
        daily_pnl=-10.20,
        daily_pnl_pct=-2.04,
        equity=489.80,
    )
    assert "LIMITĂ ZILNICĂ ATINSĂ [PAPER] (−2,00%)" in loss_alert
    assert "−10,20 $ (−2,04%)" in loss_alert
    assert "a oprit orice tranzacție nouă pentru restul zilei" in loss_alert


def test_format_kill_and_error():
    kill = format_kill_message(
        reason="Buton KILL apăsat din dashboard",
        equity=492.50,
        closed_positions=1,
    )
    assert "OPRIRE DE URGENȚĂ (KILL) [PAPER]" in kill
    assert "Poziții închise la piață: 1" in kill
    assert "492,50 $" in kill

    err = format_error_message(component="date IEX", error="Conexiune întreruptă")
    assert "EROARE BOT [PAPER]" in err
    assert "Componentă: date IEX" in err
    assert "Conexiune întreruptă" in err


def test_fetch_chat_id_from_get_updates():
    updates = {
        "ok": True,
        "result": [
            {"update_id": 1, "message": {"chat": {"id": 111222333, "type": "private"}}},
            {"update_id": 2, "message": {"chat": {"id": 999888777, "type": "private"}}},
        ],
    }
    session = _FakeSession(get_resp=_FakeResponse(200, updates))
    cid = fetch_chat_id(token="fake-token", session=session)
    assert cid == "999888777"
    assert len(session.gets) == 1


def test_send_telegram_message_auto_discovers_chat_id():
    updates = {
        "ok": True,
        "result": [{"update_id": 10, "message": {"chat": {"id": 123456789}}}],
    }
    session = _FakeSession(get_resp=_FakeResponse(200, updates))
    ok = send_telegram_message("Salut!", token="fake-token", chat_id="", session=session)
    assert ok is True
    assert len(session.gets) == 1
    assert len(session.posts) == 1
    _, body = session.posts[0]
    assert body["chat_id"] == "123456789"
    assert body["text"] == "Salut!"


def test_send_helpers_and_failure_modes():
    session = _FakeSession()
    assert send_entry_alert(
        token="t",
        chat_id="42",
        session=session,
        symbol="SPY",
        direction="long",
        qty=1.0,
        entry_price=580.0,
        stop=577.0,
        risk_pct=0.005,
        reason="Test",
    )
    assert send_exit_alert(
        token="t",
        chat_id="42",
        session=session,
        symbol="SPY",
        direction="long",
        pnl=1.5,
        r_multiple=0.8,
        exit_reason="eod",
    )
    assert send_daily_summary_alert(
        token="t",
        chat_id="42",
        session=session,
        date="2026-11-04",
        equity=501.5,
        daily_pnl=1.5,
        daily_pnl_pct=0.3,
        total_pnl=1.5,
        total_pnl_pct=0.3,
        trades_count=1,
        wins_count=1,
    )
    assert send_daily_loss_limit_alert(
        token="t",
        chat_id="42",
        session=session,
        daily_pnl=-10.0,
        daily_pnl_pct=-2.0,
        equity=490.0,
    )
    assert send_kill_alert(token="t", chat_id="42", session=session, reason="Test kill")
    assert send_error_alert(
        token="t", chat_id="42", session=session, component="test", error="eroare"
    )
    assert len(session.posts) == 6

    # Missing token or HTTP 500 returns False cleanly
    assert send_telegram_message("x", token="", chat_id="42", session=session) is False
    bad_session = _FakeSession(post_resp=_FakeResponse(500, {"ok": False}))
    assert send_telegram_message("x", token="t", chat_id="42", session=bad_session) is False
