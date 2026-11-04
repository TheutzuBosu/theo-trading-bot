"""Regression tests for the B6d live-execution audit (offline, no network).

Each test pins one bug found in the B6c live runner:
- hourly multipliers written as "09:00" crashed the next trading step (int("09:00"));
- D1b only fires on fixed check bars, so a run must find the latest fresh check-bar signal;
- the -2% daily loss rule must use the broker's previous close equity;
- closed trades must be recorded (trades.csv, autopsy, meta dataset) for the daily learning;
- the stop only tightens (VWAP trail), the D1b time exit flattens at 15:30 ET;
- GitHub Actions starts with an empty state/, so state is restored from the `state` branch and
  routine syncs never overwrite kill_switch.json.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from src.ai.daily_learner import compute_hourly_multipliers
from src.broker.alpaca_paper import AlpacaPaperAdapter
from src.live.runner import (
    _parse_hourly_multipliers,
    d1b_event_times,
    evaluate_symbol_candidate,
    find_fresh_d1b_signal,
    plan_auto_run,
    run_kill_switch,
    run_scheduled_cycle,
    run_trading_step,
    session_bounds,
    translate_signal_stop,
)
from src.live.state_writer import (
    KILL_SWITCH_FILE,
    ROUTINE_SYNC_FILES,
    fetch_remote_kill_switch,
    pull_state_dir_from_github,
)
from src.state.store import StateStore
from tests.live_fakes import FakeAlpaca, make_intraday_bars

NY = ZoneInfo("America/New_York")
NOW_CHECK = datetime(2026, 10, 22, 10, 12, 8, tzinfo=NY)
PRICES = {"SSO": 80.0, "QID": 30.0, "SDS": 56.0, "SH": 33.0, "PSQ": 27.0, "QLD": 81.0}


class _Resp:
    def __init__(self, status_code: int, text: str | None = None, payload: Any = None) -> None:
        self.status_code = status_code
        self.text = text
        self._payload = payload if payload is not None else {}

    def json(self) -> Any:
        return self._payload


class FakeGitHub:
    """Serves `state/<file>` from an in-memory branch and records uploads."""

    def __init__(self, files: dict[str, str] | None = None) -> None:
        self.files = dict(files or {})
        self.puts: list[str] = []

    def get(self, url: str, headers: Any = None, params: Any = None, timeout: int = 10) -> _Resp:
        if url.endswith("/git/ref/heads/state"):
            return _Resp(200, payload={"object": {"sha": "s"}})
        if "/contents/state/" in url:
            name = url.split("/contents/state/")[1]
            if name not in self.files:
                return _Resp(404, text="")
            raw = (headers or {}).get("Accept", "").endswith("raw")
            return _Resp(200, text=self.files[name] if raw else None, payload={"sha": "x"})
        if "finnhub.io" in url:
            return _Resp(200, payload=[])
        return _Resp(404, text="")

    def put(self, url: str, headers: Any = None, json: Any = None, timeout: int = 10) -> _Resp:
        name = url.split("/contents/state/")[1]
        self.puts.append(name)
        self.files[name] = base64.b64decode(json["content"]).decode("utf-8")
        return _Resp(200, payload={})

    def post(self, url: str, headers: Any = None, json: Any = None, timeout: int = 10) -> _Resp:
        return _Resp(200, payload={"ok": True})


def _adapter(client: FakeAlpaca, tmp_path: Path) -> AlpacaPaperAdapter:
    return AlpacaPaperAdapter(client, root_dir=tmp_path, sleep=lambda _s: None)


def _step(tmp_path: Path, adapter: AlpacaPaperAdapter, bars: dict, now: datetime, **kw: Any):
    return run_trading_step(
        state_dir=tmp_path,
        adapter=adapter,
        bars_by_symbol=bars,
        leverage=kw.pop("leverage", 2),
        send_alerts=False,
        http_session=kw.pop("http_session", FakeGitHub()),
        prices=kw.pop("prices", PRICES),
        now_et=now,
        **kw,
    )


# --------------------------------------------------------------------- learning stats
def test_hourly_multipliers_written_by_eod_are_parsed_without_crash(tmp_path: Path) -> None:
    assert _parse_hourly_multipliers({"09:00": 0.5, "10": 0.8, 11: 1.0, "x": 2}) == {
        9: 0.5,
        10: 0.8,
        11: 1.0,
    }
    StateStore(tmp_path).write_learning_stats({"hourly_multipliers": {"10:00": 0.7}})
    client = FakeAlpaca(prices=PRICES)
    bars = {"SPY": make_intraday_bars(breakout_last_day="long")}
    step = _step(tmp_path, _adapter(client, tmp_path), bars, NOW_CHECK)
    assert step["status"] == "ok"
    assert "0.70" in step["decisions"]["SPY"]["reason"]  # mult_oră=0.70 applied


def test_hourly_multipliers_accept_mixed_dst_offsets() -> None:
    trades = pd.DataFrame(
        {
            "entry_time": ["2026-10-30T10:12:00-04:00"] * 3 + ["2026-11-04T10:12:00-05:00"] * 3,
            "r_multiple": [-0.4] * 6,
        }
    )
    mults = compute_hourly_multipliers(trades)
    assert mults["10:00"] == 0.6


# ----------------------------------------------------------------- signal timing
def test_d1b_event_times_regular_and_early_close() -> None:
    reg = session_bounds(datetime(2026, 11, 4, 9, 0, tzinfo=NY))
    ev = d1b_event_times(*reg)
    assert [t.strftime("%H:%M") for t in ev["checks"]] == [
        "10:12",
        "10:58",
        "11:44",
        "12:30",
        "13:16",
        "14:02",
        "14:48",
    ]
    assert ev["time_exit"].strftime("%H:%M") == "15:30"
    early = d1b_event_times(*session_bounds(datetime(2026, 11, 27, 9, 0, tzinfo=NY)))
    assert [t.strftime("%H:%M") for t in early["checks"]] == ["10:12", "10:58", "11:44"]
    assert early["time_exit"].strftime("%H:%M") == "12:30"
    assert session_bounds(datetime(2026, 11, 26, 12, 0, tzinfo=NY)) is None  # Thanksgiving


def test_plan_auto_run_waits_for_next_check_and_handles_closed_market() -> None:
    plan = plan_auto_run(datetime(2026, 11, 4, 10, 5, tzinfo=NY))
    assert plan["action"] == "wait"
    assert 7 * 60 < plan["sleep_s"] < 8 * 60  # until 10:12:00 + settle seconds
    assert plan_auto_run(datetime(2026, 11, 4, 9, 5, tzinfo=NY))["action"] == "closed"
    assert plan_auto_run(datetime(2026, 11, 26, 11, 0, tzinfo=NY))["action"] == "closed"
    assert plan_auto_run(datetime(2026, 11, 4, 9, 51, tzinfo=NY))["action"] == "run"
    assert plan_auto_run(datetime(2026, 11, 4, 15, 31, tzinfo=NY))["action"] == "run"


def test_fresh_signal_window_and_late_bars() -> None:
    # Last bar is 10:20 (signal bar 10:11 is no longer the last bar): still found until 10:22
    bars = make_intraday_bars(breakout_last_day="long", cut_at_minute=50)
    found = find_fresh_d1b_signal(bars, datetime(2026, 10, 22, 10, 21, tzinfo=NY))
    assert found is not None
    assert found[0].strftime("%H:%M") == "10:11"
    assert find_fresh_d1b_signal(bars, datetime(2026, 10, 22, 10, 23, tzinfo=NY)) is None


# ------------------------------------------------------------------- daily loss rule
def test_daily_loss_limit_uses_broker_last_equity(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    store.write_equity(
        pd.DataFrame(
            [
                {"date": "2026-10-21", "bot_equity": 500.0, "spy_buy_hold": 500.0,
                 "daily_pnl": 0.0, "drawdown_pct": 0.0},
                {"date": "2026-10-22", "bot_equity": 489.0, "spy_buy_hold": 500.0,
                 "daily_pnl": -11.0, "drawdown_pct": -2.2},
            ]
        )
    )  # fmt: skip
    client = FakeAlpaca(prices=PRICES, equity=489.0, last_equity=500.0)  # -2.2% today
    bars = {"SPY": make_intraday_bars(breakout_last_day="long")}
    step = _step(tmp_path, _adapter(client, tmp_path), bars, NOW_CHECK)
    assert step["orders"] == []
    assert "-2%" in step["decisions"]["SPY"]["reason"]
    assert StateStore(tmp_path).read_summary()["today_pnl"] == -11.0


# ------------------------------------------------- idempotency, recording, management
def test_second_run_does_not_duplicate_and_stop_hit_is_recorded(tmp_path: Path) -> None:
    client = FakeAlpaca(prices=PRICES)
    adapter = _adapter(client, tmp_path)
    bars = {"SPY": make_intraday_bars(breakout_last_day="long")}
    first = _step(tmp_path, adapter, bars, NOW_CHECK)
    assert [o["exec_symbol"] for o in first["orders"]] == ["SSO"]

    again = _step(tmp_path, _adapter(client, tmp_path), bars, NOW_CHECK.replace(second=40))
    assert again["orders"] == []  # processed signal + open SPY family position

    stop_px = client.open_stop("SSO").stop_price
    client.prices["SSO"] = stop_px - 0.05
    client.trigger_stop("SSO", stop_px)
    later = _step(tmp_path, _adapter(client, tmp_path), bars, NOW_CHECK.replace(minute=30))
    assert len(later["closed"]) == 1
    trade = later["closed"][0]
    assert trade["exit_reason"] == "stop"
    assert trade["pnl"] < 0
    store = StateStore(tmp_path)
    assert len(store.read_trades()) == 1
    assert "Lecție:" in str(store.read_trades().iloc[0]["entry_reason"])
    assert len(store.read_autopsies()) == 1
    assert len(store.read_meta_dataset()) == 1
    assert store.read_journal()["open_trades"] == {}


def test_vwap_trail_only_tightens_and_time_exit_flattens(tmp_path: Path) -> None:
    client = FakeAlpaca(prices=PRICES)
    adapter = _adapter(client, tmp_path)
    bars_entry = make_intraday_bars(breakout_last_day="long")
    _step(tmp_path, adapter, {"SPY": bars_entry}, NOW_CHECK)
    tr = StateStore(tmp_path).read_journal()["open_trades"]["SSO"]
    initial_exec_stop = tr["exec_stop"]

    # Later the session VWAP rises above the D1b stop: the stop is raised, never lowered
    bars_later = bars_entry.copy()
    extra_idx = pd.date_range("2026-10-22 10:12", periods=30, freq="1min", tz=NY)
    extra = pd.DataFrame(
        {
            "open": 584.6, "high": 584.8, "low": 584.4, "close": 584.6,
            "volume": 5_000_000.0, "trade_count": 400.0, "vwap": 584.6,
        },
        index=extra_idx,
    )  # fmt: skip
    bars_later = pd.concat([bars_later, extra])
    mid = _step(
        tmp_path,
        _adapter(client, tmp_path),
        {"SPY": bars_later},
        datetime(2026, 10, 22, 10, 42, 30, tzinfo=NY),
    )
    assert any(a["action"] == "trail" for a in mid["management"])
    new_stop = StateStore(tmp_path).read_journal()["open_trades"]["SSO"]["exec_stop"]
    assert new_stop > initial_exec_stop
    assert client.open_stop("SSO").stop_price == new_stop
    assert client.open_stop("SSO").client_order_id.endswith("-SL")  # fill -> exit_reason "stop"

    # 15:30 ET: D1b time exit closes everything and records the reason
    end = _step(
        tmp_path,
        _adapter(client, tmp_path),
        {"SPY": bars_later},
        datetime(2026, 10, 22, 15, 30, 10, tzinfo=NY),
    )
    assert client.positions == {}
    assert end["closed"][0]["exit_reason"] == "time"


def test_translate_signal_stop_for_inverse_and_leveraged_etfs() -> None:
    # Short SPY at 600 with stop 603 (+0.5%) via SDS (-2x) at 50 -> stop 1% below 50
    assert (
        translate_signal_stop(
            signal_stop=603.0,
            signal_price=600.0,
            exec_price=50.0,
            leverage=2,
            signal_direction="short",
            same_instrument=False,
        )
        == 49.5
    )
    # Long SPY itself: the stop is the D1b stop
    assert (
        translate_signal_stop(
            signal_stop=597.123,
            signal_price=600.0,
            exec_price=600.0,
            leverage=1,
            signal_direction="long",
            same_instrument=True,
        )
        == 597.12
    )


def test_missing_etf_price_skips_instead_of_using_spy_price() -> None:
    cand = evaluate_symbol_candidate(
        "QQQ",
        make_intraday_bars(breakout_last_day="short"),
        equity=500.0,
        open_positions=set(),
        current_exposure=0.0,
        daily_pnl_pct=0.0,
        drawdown_pct=0.0,
        leverage=2,
        etf_prices={},
        now_et=NOW_CHECK,
        http_session=FakeGitHub(),
    )
    assert cand["action"] == "skip"
    assert "QID" in cand["reason"]


# ----------------------------------------------------------- state branch + KILL
def test_state_restored_from_branch_and_kill_switch_not_overwritten(tmp_path: Path) -> None:
    gh = FakeGitHub(
        {
            "kill_switch.json": json.dumps({"active": True, "reason": "test"}),
            "trades.csv": "symbol,pnl\nSSO,1.5\n",
        }
    )
    res = pull_state_dir_from_github(tmp_path, token="t", session=gh)
    assert res["kill_switch.json"] is True and res["trades.csv"] is True
    assert StateStore(tmp_path).read_kill_switch()["active"] is True
    assert fetch_remote_kill_switch(token="t", session=gh) is True

    client = FakeAlpaca(prices=PRICES)
    client.positions["SSO"] = {"qty": 1.0, "avg": 80.0}
    step = run_trading_step(
        state_dir=tmp_path,
        adapter=_adapter(client, tmp_path),
        bars_by_symbol={"SPY": make_intraday_bars()},
        send_alerts=False,
        sync_github=True,
        github_token="t",
        http_session=gh,
        prices=PRICES,
        now_et=NOW_CHECK,
    )
    assert step["status"] == "halted"
    assert client.positions == {}  # KILL active -> stay flat
    assert KILL_SWITCH_FILE not in ROUTINE_SYNC_FILES
    assert KILL_SWITCH_FILE not in gh.puts  # routine sync never uploads kill_switch.json


def test_kill_switch_uploads_kill_file(tmp_path: Path) -> None:
    gh = FakeGitHub()
    client = FakeAlpaca(prices=PRICES)
    run_kill_switch(
        state_dir=tmp_path,
        adapter=_adapter(client, tmp_path),
        reason="test",
        sync_github=True,
        github_token="t",
        send_alerts=False,
        http_session=gh,
        now_et=NOW_CHECK,
    )
    assert json.loads(gh.files[KILL_SWITCH_FILE])["active"] is True


def test_scheduled_cycle_runs_eod_once_after_time_exit(tmp_path: Path) -> None:
    client = FakeAlpaca(prices=PRICES)
    adapter = _adapter(client, tmp_path)
    clock = {"now": datetime(2026, 10, 22, 15, 31, tzinfo=NY)}

    def cycle() -> dict[str, Any]:
        return run_scheduled_cycle(
            state_dir=tmp_path,
            adapter=adapter,
            load_bars=lambda: {"SPY": make_intraday_bars()},
            load_prices=lambda: PRICES,
            now_fn=lambda: clock["now"],
            sleep_fn=lambda _s: None,
            http_session=FakeGitHub(),
            send_alerts=False,
        )

    client.positions["SSO"] = {"qty": 1.0, "avg": 80.0}
    first = cycle()
    assert "eod" in first
    assert client.positions == {}
    assert StateStore(tmp_path).read_journal()["last_eod_date"] == "2026-10-22"
    clock["now"] = datetime(2026, 10, 22, 15, 50, tzinfo=NY)
    assert "eod" not in cycle()
