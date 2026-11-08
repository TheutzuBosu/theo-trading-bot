"""B6f critical fixes: single-engine lease, live window, orphan protection, fill-anchored stops,
fail-closed scanner, persisted scan cooldown, fresh prices (all offline)."""

from __future__ import annotations

import base64
import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from src.ai import market_scanner as ms
from src.broker.alpaca_paper import AlpacaPaperAdapter
from src.live import state_writer as sw
from src.live.runner import (
    fit_meta_model_from_dataset,
    live_window,
    protect_orphan_positions,
)
from src.state.store import StateStore
from tests.live_fakes import FakeAlpaca

NY = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------ fake GitHub lock store
class _Resp:
    def __init__(self, status: int, payload: Any = None) -> None:
        self.status_code = status
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class FakeLockGitHub:
    """Contents API for state/engine_lock.json with real compare-and-swap on the blob sha."""

    def __init__(self) -> None:
        self.data: dict[str, Any] | None = None
        self.sha_n = 0
        self.puts = 0
        self.fail_get = False

    @property
    def sha(self) -> str:
        return f"sha-{self.sha_n}"

    def get(self, url: str, **_kw: Any) -> _Resp:
        if self.fail_get:
            raise ConnectionError("offline")
        if self.data is None:
            return _Resp(404, {})
        content = base64.b64encode(json.dumps(self.data).encode()).decode()
        return _Resp(200, {"content": content, "sha": self.sha})

    def put(self, url: str, json: dict[str, Any], **_kw: Any) -> _Resp:  # noqa: A002
        self.puts += 1
        if self.data is not None and json.get("sha") != self.sha:
            return _Resp(409, {})
        if self.data is None and json.get("sha"):
            return _Resp(409, {})
        self.data = __import__("json").loads(base64.b64decode(json["content"]).decode())
        self.sha_n += 1
        return _Resp(200, {})


T0 = datetime(2026, 11, 9, 15, 0, tzinfo=UTC)


def test_lease_acquire_renew_block_takeover_release() -> None:
    gh = FakeLockGitHub()
    a = sw.acquire_engine_lease("A", token="t", session=gh, now=T0)
    assert a["held"] is True and a["fresh"] is True
    assert gh.data["holder"] == "A"

    # Another engine is blocked while A's lease is valid
    b = sw.acquire_engine_lease("B", token="t", session=gh, now=T0 + timedelta(seconds=30))
    assert b["held"] is False and b["holder"] == "A"

    # A with plenty of time left: no write; close to expiry: renewed (not fresh)
    puts = gh.puts
    a2 = sw.acquire_engine_lease("A", token="t", session=gh, now=T0 + timedelta(seconds=60))
    assert a2["held"] is True and a2["fresh"] is False and gh.puts == puts
    a3 = sw.acquire_engine_lease("A", token="t", session=gh, now=T0 + timedelta(seconds=120))
    assert a3["held"] is True and a3["fresh"] is False and gh.puts == puts + 1

    # Expired lease: B takes over and must reload the whole state
    late = T0 + timedelta(seconds=120 + sw.LEASE_TTL_S + 1)
    b2 = sw.acquire_engine_lease("B", token="t", session=gh, now=late)
    assert b2["held"] is True and b2["fresh"] is True and gh.data["holder"] == "B"

    # A cannot release B's lease; B can
    assert sw.release_engine_lease("A", token="t", session=gh, now=late) is False
    assert sw.release_engine_lease("B", token="t", session=gh, now=late) is True
    assert gh.data["holder"] == ""
    c = sw.acquire_engine_lease("C", token="t", session=gh, now=late)
    assert c["held"] is True and c["fresh"] is True


def test_lease_cas_conflict_and_network_error() -> None:
    gh = FakeLockGitHub()
    sw.acquire_engine_lease("A", token="t", session=gh, now=T0)
    real_get = gh.get

    def racing_get(url: str, **kw: Any) -> _Resp:
        resp = real_get(url, **kw)
        gh.sha_n += 1  # someone else writes between our GET and PUT
        return resp

    gh.get = racing_get  # type: ignore[method-assign]
    late = T0 + timedelta(seconds=sw.LEASE_TTL_S + 5)
    res = sw.acquire_engine_lease("B", token="t", session=gh, now=late)
    assert res["held"] is False and not res.get("error")

    gh.get = real_get  # type: ignore[method-assign]
    gh.fail_get = True
    err = sw.acquire_engine_lease("B", token="t", session=gh, now=late)
    assert err["held"] is False and err["error"] is True


def test_lease_disabled_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sw, "_resolve_token", lambda _t: "")
    assert sw.acquire_engine_lease("A", token=None)["held"] is True


class FakePushSession:
    def __init__(self) -> None:
        self.puts: list[str] = []

    def get(self, url: str, **_kw: Any) -> _Resp:
        if "/git/ref" in url or url.endswith("/branches/state"):
            return _Resp(200, {"object": {"sha": "x"}})
        return _Resp(404, {})

    def put(self, url: str, **_kw: Any) -> _Resp:
        self.puts.append(url.rsplit("/", 1)[-1])
        return _Resp(201, {})

    def post(self, url: str, **_kw: Any) -> _Resp:
        return _Resp(201, {})


def test_push_dedupe_skips_unchanged_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sw, "ensure_github_state_branch", lambda *a, **k: True)
    monkeypatch.setattr(sw, "_LAST_SYNCED", {})
    (tmp_path / "summary.json").write_text('{"a": 1}', encoding="utf-8")
    session = FakePushSession()
    sw.enable_push_dedupe(True)
    try:
        sw.sync_state_dir_to_github(tmp_path, token="t", session=session, files=("summary.json",))
        sw.sync_state_dir_to_github(tmp_path, token="t", session=session, files=("summary.json",))
        assert session.puts == ["summary.json"]
        (tmp_path / "summary.json").write_text('{"a": 2}', encoding="utf-8")
        sw.sync_state_dir_to_github(tmp_path, token="t", session=session, files=("summary.json",))
        assert session.puts == ["summary.json", "summary.json"]
    finally:
        sw.enable_push_dedupe(False)


# --------------------------------------------------------------------------- live window
@pytest.mark.parametrize(
    ("ts", "active", "relay"),
    [
        (datetime(2026, 11, 26, 10, 0, tzinfo=NY), False, False),  # Thanksgiving: closed
        (datetime(2026, 11, 27, 12, 30, tzinfo=NY), True, True),  # early close 13:00
        (datetime(2026, 11, 27, 12, 50, tzinfo=NY), True, False),
        (datetime(2026, 11, 27, 13, 6, tzinfo=NY), False, False),
        (datetime(2026, 11, 9, 7, 59, tzinfo=NY), False, False),
        (datetime(2026, 11, 9, 8, 0, tzinfo=NY), True, False),  # pre-market only
        (datetime(2026, 11, 9, 9, 0, tzinfo=NY), True, True),
        (datetime(2026, 11, 9, 15, 44, tzinfo=NY), True, True),
        (datetime(2026, 11, 9, 15, 46, tzinfo=NY), True, False),
        (datetime(2026, 11, 9, 16, 5, tzinfo=NY), False, False),
        (datetime(2026, 11, 7, 10, 0, tzinfo=NY), False, False),  # Saturday
    ],
)
def test_live_window(ts: datetime, active: bool, relay: bool) -> None:
    w = live_window(ts)
    assert w["active"] is active
    assert w["relay"] is relay


# ------------------------------------------------------------------- orphan positions
def _adapter(client: FakeAlpaca, tmp_path: Path) -> AlpacaPaperAdapter:
    return AlpacaPaperAdapter(client, root_dir=tmp_path, sleep=lambda _s: None)


def test_orphan_without_stop_is_closed_and_orphan_with_stop_is_kept(tmp_path: Path) -> None:
    client = FakeAlpaca(prices={"AMD": 150.0, "NVDA": 140.0, "SSO": 80.0})
    adapter = _adapter(client, tmp_path)
    client.positions = {
        "AMD": {"qty": 0.1, "avg": 150.0},  # orphan, no stop
        "NVDA": {"qty": 0.1, "avg": 140.0},  # orphan with resting stop
        "SSO": {"qty": 0.2, "avg": 80.0},  # known by the journal
    }
    client.submit_order(
        __import__("alpaca.trading.requests", fromlist=["StopOrderRequest"]).StopOrderRequest(
            symbol="NVDA",
            qty=0.1,
            side="sell",
            time_in_force="day",
            stop_price=136.0,
            client_order_id="stop-nvda",
        )
    )
    journal = {"open_trades": {"SSO": {"exec_symbol": "SSO"}}}
    actions = protect_orphan_positions(adapter, journal, adapter.get_open_positions())
    by_sym = {a["symbol"]: a["action"] for a in actions}
    assert by_sym == {"AMD": "close_orphan", "NVDA": "orphan_has_stop"}
    assert "AMD" not in client.positions
    assert "NVDA" in client.positions and "SSO" in client.positions


# ----------------------------------------------------------------- fill-anchored stops
def test_stop_is_re_anchored_on_real_fill(tmp_path: Path) -> None:
    client = FakeAlpaca(prices={"DUOG": 9.10})
    adapter = _adapter(client, tmp_path)
    # Stop computed from a stale 10.00 quote (2% under it) would sit at 9.80, above the 9.10 fill
    res = adapter.submit_entry_with_stop(
        symbol="DUOG",
        qty=1.0,
        stop_price=9.80,
        client_order_id="entry-duog",
        stop_from_fill_pct=0.02,
    )
    assert res["stop_price"] == pytest.approx(round(9.10 * 0.98, 2))
    stop = client.open_stop("DUOG")
    assert stop is not None and float(stop.stop_price) == pytest.approx(8.92)


def test_stop_from_fill_pct_bounds(tmp_path: Path) -> None:
    adapter = _adapter(FakeAlpaca(prices={"SPY": 600.0}), tmp_path)
    with pytest.raises(ValueError):
        adapter.submit_entry_with_stop(
            symbol="SPY", qty=0.1, stop_price=590.0, client_order_id="x", stop_from_fill_pct=0.3
        )


def test_short_without_dedicated_inverse_is_refused() -> None:
    from src.broker.alpaca_paper import resolve_execution_instrument

    with pytest.raises(ValueError):
        resolve_execution_instrument(
            symbol="INTC",
            direction="short",
            qty=1.0,
            entry_price=22.0,
            stop_price=22.4,
            target_price=20.0,
            leverage=1,
            account_equity=500.0,
            shorting_enabled=False,
            instrument_price=25.0,
        )


# ------------------------------------------------------------------- fail-closed scanner
GOOD_ASSET = {
    "status": "active",
    "tradable": True,
    "fractionable": True,
    "exchange": "NASDAQ",
    "name": "Advanced Micro Devices, Inc.",
}


def test_check_tradable_asset_fail_closed() -> None:
    assert ms.check_tradable_asset(None)[0] is False
    assert ms.check_tradable_asset(GOOD_ASSET) == (True, "")
    assert ms.check_tradable_asset({**GOOD_ASSET, "fractionable": False})[0] is False
    assert ms.check_tradable_asset({**GOOD_ASSET, "exchange": "OTC"})[0] is False
    assert ms.check_tradable_asset({**GOOD_ASSET, "status": "inactive"})[0] is False
    lev = {**GOOD_ASSET, "name": "Direxion Daily Semiconductor Bear 3X Shares"}
    assert ms.check_tradable_asset(lev)[0] is False
    assert ms.check_tradable_asset({**GOOD_ASSET, "name": "ProShares UltraPro QQQ"})[0] is False


def test_symbol_filters_and_proxy_map() -> None:
    assert ms.is_valid_stock_symbol("AMD") is True
    assert ms.is_valid_stock_symbol("ABCDQ") is False  # bankruptcy suffix
    assert ms.is_valid_stock_symbol("RGTIW") is False  # warrant
    assert ms.resolve_short_proxy_symbol("NVDA") == "NVD"
    assert ms.resolve_short_proxy_symbol("INTC") is None
    assert ms.PROXY_LEVERAGE["NVD"] == 2


def test_mover_without_gemini_or_cheap_stays_on_watch() -> None:
    mover = {"symbol": "AMD", "price": 150.0, "prev_close": 140.0, "gap_pct": 7.1}
    ev = ms.evaluate_mover_opportunity(mover, headlines=[], gemini_client=None, check_asset=False)
    assert ev["action"] == "watch"
    cheap = {"symbol": "PENY", "price": 1.6, "prev_close": 1.25, "gap_pct": 28.0}
    assert ms.evaluate_mover_opportunity(cheap, headlines=[], check_asset=False)["action"] == (
        "watch"
    )


class _FakeGemini:
    def __init__(self, text: str) -> None:
        self.models = SimpleNamespace(generate_content=lambda **_kw: SimpleNamespace(text=text))


def test_mover_requires_explicit_gemini_enter() -> None:
    mover = {"symbol": "AMD", "price": 150.0, "prev_close": 140.0, "gap_pct": 7.1}
    no = ms.evaluate_mover_opportunity(
        mover, headlines=[], gemini_client=_FakeGemini('{"enter": false}'), check_asset=False
    )
    assert no["action"] == "watch"
    bad = ms.evaluate_mover_opportunity(
        mover, headlines=[], gemini_client=_FakeGemini("not json"), check_asset=False
    )
    assert bad["action"] == "watch"


def test_scan_caps_and_spaces_ai_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    movers = [
        {"symbol": f"S{i}", "price": 50.0, "prev_close": 45.0, "gap_pct": 10.0} for i in range(10)
    ]
    monkeypatch.setattr(ms, "discover_market_movers", lambda **_kw: movers)
    monkeypatch.setattr(ms, "_load_learning_context", lambda _d: ([], ""))
    calls: list[str] = []

    def fake_eval(m: dict[str, Any], **_kw: Any) -> dict[str, Any]:
        calls.append(m["symbol"])
        return {"action": "watch", "symbol": m["symbol"], "_ai_called": True}

    monkeypatch.setattr(ms, "evaluate_mover_opportunity", fake_eval)
    sleeps: list[float] = []
    res = ms.scan_market_opportunities(max_ai_evals=3, ai_spacing_s=4.5, sleep_fn=sleeps.append)
    assert calls == ["S0", "S1", "S2"]
    assert sleeps == [4.5, 4.5]
    assert all("_ai_called" not in w for w in res["watched"])


# --------------------------------------------------------------------- meta-label dataset
def test_meta_dataset_ignores_scanner_rows_and_duplicates(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    rows = []
    for i in range(30):
        rows.append({"signal_time": f"2026-11-0{1 + i % 5}T10:{i:02d}", "symbol": "SPY"})
        rows.append({"signal_time": f"2026-11-0{1 + i % 5}T10:{i:02d}", "symbol": "SPY"})  # dup
        rows.append({"signal_time": f"2026-11-0{1 + i % 5}T11:{i:02d}", "symbol": "AMD"})
    df = pd.DataFrame(rows)
    df["r_multiple"] = [1.0 if i % 2 else -1.0 for i in range(len(df))]
    df.to_csv(store.meta_dataset_path, index=False)
    model, info = fit_meta_model_from_dataset(store)
    assert model is None
    assert info["meta_samples"] == 30  # 30 unique SPY rows < 40: filter stays off


# ------------------------------------------------------------- session script helpers
def _load_script() -> Any:
    spec = importlib.util.spec_from_file_location(
        "run_intraday_session_b6f", ROOT / "scripts" / "run_intraday_session.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_fresh_prices_drop_stale_trades_during_session() -> None:
    mod = _load_script()
    now = datetime(2026, 11, 9, 15, 30, tzinfo=UTC)  # 10:30 ET
    latest = {
        "SPY": SimpleNamespace(price=600.0, timestamp=now - timedelta(seconds=20)),
        "DUOG": SimpleNamespace(price=10.0, timestamp=now - timedelta(hours=3)),
    }
    out = mod._fresh_prices(latest, ["SPY", "DUOG"], now)
    assert out == {"SPY": 600.0}


def test_opportunity_scan_cooldown_is_persisted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mod = _load_script()
    store = StateStore(tmp_path)
    store.write_summary({"equity": 500.0})
    calls: list[int] = []

    def fake_scan(**_kw: Any) -> dict[str, Any]:
        calls.append(1)
        return {"opportunities": [], "top_movers": []}  # empty scan must still start the cooldown

    monkeypatch.setattr(mod, "scan_market_opportunities", fake_scan)
    now = datetime(2026, 11, 9, 15, 30, tzinfo=UTC)
    mod._load_opportunities(tmp_path, None, now_utc=now)
    mod._load_opportunities(tmp_path, None, now_utc=now + timedelta(minutes=5))
    assert len(calls) == 1
    mod._load_opportunities(tmp_path, None, now_utc=now + timedelta(minutes=11))
    assert len(calls) == 2
    assert store.read_summary()["premarket"]["last_scan_at"]


def test_old_opportunities_are_not_executed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mod = _load_script()
    now = datetime(2026, 11, 9, 15, 30, tzinfo=UTC)
    old = {
        "symbol": "AMD",
        "action": "enter",
        "evaluated_at": (now - timedelta(hours=20)).isoformat(),
    }
    new = {
        "symbol": "NVDA",
        "action": "enter",
        "evaluated_at": (now - timedelta(minutes=5)).isoformat(),
    }
    store = StateStore(tmp_path)
    store.write_summary(
        {"premarket": {"opportunities": [old, new], "last_scan_at": now.isoformat()}}
    )
    monkeypatch.setattr(mod, "scan_market_opportunities", lambda **_kw: pytest.fail("no scan"))
    out = mod._load_opportunities(tmp_path, None, now_utc=now + timedelta(minutes=1))
    assert [o["symbol"] for o in out] == ["NVDA"]


def test_premarket_telegram_sent_once_per_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mod = _load_script()
    StateStore(tmp_path).write_summary({"equity": 500.0})
    sent: list[str] = []
    monkeypatch.setattr(mod, "_compute_premarket_quotes", lambda _c: {})
    monkeypatch.setattr(mod, "scan_market_opportunities", lambda **_kw: {"opportunities": []})
    monkeypatch.setattr(mod, "build_premarket_briefing", lambda **_kw: {"headline": "x"})
    monkeypatch.setattr(mod, "format_premarket_telegram_message", lambda b: "msg")
    monkeypatch.setattr(mod, "send_telegram_message", lambda m: sent.append(m))
    for _ in range(3):
        mod._run_premarket_intelligence(
            state_dir=tmp_path, data_client=None, gemini_client=None, sync_github=False
        )
    assert sent == ["msg"]


def test_low_priced_runner_above_2_dollars_is_traded() -> None:
    """D36: a 3.35 $ runner (QNTU, +1.72 $ on 6.11.2026) passes the floor; 1.60 $ does not."""
    from src.live.runner import evaluate_mover_candidate

    now = datetime(2026, 11, 6, 12, 0, 59, tzinfo=NY)
    opp = {
        "symbol": "QNTU",
        "action": "enter",
        "direction": "long",
        "price": 3.34,
        "stop_price": 3.17,
        "rr_ratio": 6.0,
        "stake_dollars": 20.0,
        "confidence": 0.7,
        "reason_ro": "QNTU +40.9% pe volum mare.",
    }
    kw = dict(
        equity=500.0,
        open_positions=set(),
        current_exposure=0.0,
        daily_pnl_pct=0.0,
        drawdown_pct=0.0,
        now_et=now,
    )
    cand = evaluate_mover_candidate(opp, prices={"QNTU": 3.35}, **kw)
    assert cand["action"] == "enter"
    assert cand["exec_symbol"] == "QNTU"
    assert cand["stop_price"] < cand["entry_price"]
    low = evaluate_mover_candidate({**opp, "symbol": "PENY"}, prices={"PENY": 1.6}, **kw)
    assert low["action"] == "skip" and "sub minimul de 2" in low["reason"]
