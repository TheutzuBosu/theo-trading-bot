"""Atomic local state writer + GitHub `state` branch synchronization (Faza B, B6c).

Writes `state/summary.json` (`is_sample: False`), `state/equity.csv`, and `state/trades.csv`
and synchronizes them to the `state` branch on GitHub via the GitHub Contents API so that
the Vercel dashboard (`https://theo-trading-bot.vercel.app`) displays the real Alpaca Paper
account (`500,00 $` start, live equity, open positions, and trade lessons) in real time.
"""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from src.state.store import EQUITY_COLUMNS, TRADE_COLUMNS, StateStore

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
DEFAULT_GITHUB_REPO = "TheutzuBosu/theo-trading-bot"
DEFAULT_STATE_BRANCH = "state"
SYNCED_STATE_FILES = (
    "summary.json",
    "equity.csv",
    "trades.csv",
    "positions.json",
    "kill_switch.json",
    "learning_stats.json",
)


def _github_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def ensure_github_state_branch(
    token: str,
    repo: str = DEFAULT_GITHUB_REPO,
    branch: str = DEFAULT_STATE_BRANCH,
    base_branch: str = "main",
    session: Any | None = None,
    timeout: int = 10,
) -> bool:
    """Ensure the `state` branch exists on GitHub, creating it from `main` if missing."""
    clean_token = (token or "").strip()
    if not clean_token:
        return False

    http = session or requests
    headers = _github_headers(clean_token)
    ref_url = f"{GITHUB_API_BASE}/repos/{repo}/git/ref/heads/{branch}"

    try:
        resp = http.get(ref_url, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            return True
        if resp.status_code != 404:
            logger.warning("GitHub branch check returned HTTP %s", resp.status_code)
            return False

        base_url = f"{GITHUB_API_BASE}/repos/{repo}/git/ref/heads/{base_branch}"
        base_resp = http.get(base_url, headers=headers, timeout=timeout)
        if base_resp.status_code != 200:
            logger.warning("GitHub base branch lookup failed with HTTP %s", base_resp.status_code)
            return False

        sha = base_resp.json().get("object", {}).get("sha")
        if not sha:
            return False

        create_url = f"{GITHUB_API_BASE}/repos/{repo}/git/refs"
        create_resp = http.post(
            create_url,
            headers=headers,
            json={"ref": f"refs/heads/{branch}", "sha": sha},
            timeout=timeout,
        )
        return create_resp.status_code in (200, 201)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ensure_github_state_branch error: %s", type(exc).__name__)
        return False


def push_file_to_github_branch(
    file_path: str,
    content: str,
    message: str,
    token: str,
    repo: str = DEFAULT_GITHUB_REPO,
    branch: str = DEFAULT_STATE_BRANCH,
    session: Any | None = None,
    timeout: int = 10,
) -> bool:
    """Create or update `file_path` (e.g. `state/summary.json`) on `branch` via GitHub API."""
    clean_token = (token or "").strip()
    if not clean_token:
        return False

    http = session or requests
    headers = _github_headers(clean_token)
    url = f"{GITHUB_API_BASE}/repos/{repo}/contents/{file_path}"

    existing_sha: str | None = None
    try:
        get_resp = http.get(url, headers=headers, params={"ref": branch}, timeout=timeout)
        if get_resp.status_code == 200:
            payload = get_resp.json()
            if isinstance(payload, dict):
                existing_sha = payload.get("sha")
    except Exception as exc:  # noqa: BLE001
        logger.warning("GitHub GET %s failed: %s", file_path, type(exc).__name__)

    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    body: dict[str, Any] = {
        "message": message,
        "content": encoded,
        "branch": branch,
    }
    if existing_sha:
        body["sha"] = existing_sha

    try:
        put_resp = http.put(url, headers=headers, json=body, timeout=timeout)
        if put_resp.status_code in (200, 201):
            return True
        logger.warning("GitHub PUT %s failed with HTTP %s", file_path, put_resp.status_code)
        return False
    except Exception as exc:  # noqa: BLE001
        logger.warning("GitHub PUT %s error: %s", file_path, type(exc).__name__)
        return False


def sync_state_dir_to_github(
    state_dir: Path,
    token: str | None = None,
    repo: str = DEFAULT_GITHUB_REPO,
    branch: str = DEFAULT_STATE_BRANCH,
    session: Any | None = None,
) -> dict[str, bool]:
    """Push all existing state files in `state_dir` to the `state` branch on GitHub."""
    gh_token = (
        token
        if token is not None
        else (os.environ.get("GH_DISPATCH_TOKEN") or os.environ.get("GITHUB_TOKEN") or "")
    ).strip()
    results: dict[str, bool] = {}
    if not gh_token:
        return results

    if not ensure_github_state_branch(gh_token, repo=repo, branch=branch, session=session):
        return results

    for fname in SYNCED_STATE_FILES:
        local_file = Path(state_dir) / fname
        if not local_file.exists():
            continue
        content = local_file.read_text(encoding="utf-8")
        remote_path = f"state/{fname}"
        ok = push_file_to_github_branch(
            file_path=remote_path,
            content=content,
            message=f"chore(state): actualizare {fname}",
            token=gh_token,
            repo=repo,
            branch=branch,
            session=session,
        )
        results[fname] = ok
    return results


def write_state_files(
    state_dir: Path,
    summary: dict[str, Any],
    equity_df: pd.DataFrame,
    trades_df: pd.DataFrame,
    *,
    sync_github: bool = False,
    github_token: str | None = None,
    repo: str = DEFAULT_GITHUB_REPO,
    branch: str = DEFAULT_STATE_BRANCH,
    session: Any | None = None,
) -> dict[str, bool]:
    """Write summary.json, equity.csv, and trades.csv atomically (with optional GitHub sync)."""
    store = StateStore(state_dir)
    clean_summary = dict(summary)
    clean_summary["is_sample"] = False
    store.write_summary(clean_summary)

    if equity_df.empty:
        eq_out = pd.DataFrame(columns=EQUITY_COLUMNS)
    else:
        eq_out = equity_df.copy()
        for col in EQUITY_COLUMNS:
            if col not in eq_out.columns:
                eq_out[col] = 0.0
        eq_out = eq_out[list(EQUITY_COLUMNS)]
    store.write_equity(eq_out)

    if trades_df.empty:
        tr_out = pd.DataFrame(columns=TRADE_COLUMNS)
    else:
        tr_out = trades_df.copy()
        for col in TRADE_COLUMNS:
            if col not in tr_out.columns:
                tr_out[col] = ""
        tr_out = tr_out[list(TRADE_COLUMNS)]
    store.write_trades(tr_out)

    if sync_github:
        return sync_state_dir_to_github(
            state_dir=Path(state_dir),
            token=github_token,
            repo=repo,
            branch=branch,
            session=session,
        )
    return {}
