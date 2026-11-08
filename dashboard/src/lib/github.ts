// GitHub helpers shared by the dashboard API routes (B6f).

export const DEFAULT_REPO = "TheutzuBosu/theo-trading-bot";

// Every status of a run that has not finished yet. A run waiting in the concurrency group is
// "pending"; checking only in_progress/queued made the dashboard start duplicate sessions.
export const ACTIVE_RUN_STATUSES = new Set([
  "in_progress",
  "queued",
  "pending",
  "waiting",
  "requested",
]);

export function githubHeaders(token: string): Record<string, string> {
  return {
    Authorization: `Bearer ${token}`,
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "Content-Type": "application/json",
  };
}

export function repoName(): string {
  return process.env.GITHUB_REPO || DEFAULT_REPO;
}

/** Id of an unfinished intraday_paper.yml run, or null. Throws nothing. */
export async function findActiveSessionRun(token: string): Promise<number | null> {
  try {
    const res = await fetch(
      `https://api.github.com/repos/${repoName()}/actions/workflows/intraday_paper.yml/runs?per_page=10`,
      { headers: githubHeaders(token), cache: "no-store" }
    );
    if (!res.ok) return null;
    const data = await res.json();
    const run = (data.workflow_runs || []).find((r: { status?: string }) =>
      ACTIVE_RUN_STATUSES.has(String(r.status || ""))
    );
    return run ? Number(run.id) : null;
  } catch {
    return null;
  }
}

/** Start the 15-minute relay chain (mode `session`). Returns the HTTP status (204 = started). */
export async function dispatchSession(token: string): Promise<number> {
  const res = await fetch(
    `https://api.github.com/repos/${repoName()}/actions/workflows/intraday_paper.yml/dispatches`,
    {
      method: "POST",
      headers: githubHeaders(token),
      body: JSON.stringify({ ref: "main", inputs: { mode: "session" } }),
      cache: "no-store",
    }
  );
  return res.status;
}

/**
 * Write state/kill_switch.json = active on the `state` branch directly (Contents API).
 * The running bot reads this file every minute and stops opening trades, even when the
 * kill.yml workflow cannot start. Retries once on a sha conflict.
 */
export async function writeKillSwitchFlag(token: string, reason: string): Promise<boolean> {
  const url = `https://api.github.com/repos/${repoName()}/contents/state/kill_switch.json`;
  const body = JSON.stringify(
    { active: true, reason, triggered_at: new Date().toISOString() },
    null,
    2
  );
  const content = Buffer.from(body + "\n", "utf8").toString("base64");
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const cur = await fetch(`${url}?ref=state`, {
        headers: githubHeaders(token),
        cache: "no-store",
      });
      const sha = cur.ok ? (await cur.json()).sha : undefined;
      const put = await fetch(url, {
        method: "PUT",
        headers: githubHeaders(token),
        body: JSON.stringify({
          message: "KILL din Dashboard",
          content,
          branch: "state",
          ...(sha ? { sha } : {}),
        }),
        cache: "no-store",
      });
      if (put.ok) return true;
      if (put.status !== 409 && put.status !== 422) return false;
    } catch {
      return false;
    }
  }
  return false;
}
