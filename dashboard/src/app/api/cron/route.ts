import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

async function triggerIntradaySession() {
  const ghToken = (process.env.GH_DISPATCH_TOKEN || "").trim();
  const repo = process.env.GITHUB_REPO || "TheutzuBosu/theo-trading-bot";

  if (!ghToken) {
    return NextResponse.json(
      { ok: false, error: "Lipsește GH_DISPATCH_TOKEN în variabilele de mediu Vercel." },
      { status: 500 }
    );
  }

  const headers = {
    Authorization: `Bearer ${ghToken}`,
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "Content-Type": "application/json",
  };

  try {
    // 1. Verificăm dacă există deja o sesiune activă sau în coadă pentru a nu dubla rulările
    const runsRes = await fetch(
      `https://api.github.com/repos/${repo}/actions/workflows/intraday_paper.yml/runs?per_page=5`,
      { headers, cache: "no-store" }
    );
    if (runsRes.ok) {
      const runsData = await runsRes.json();
      const activeRun = (runsData.workflow_runs || []).find(
        (r: { status?: string }) => r.status === "in_progress" || r.status === "queued"
      );
      if (activeRun) {
        return NextResponse.json({
          ok: true,
          skipped: true,
          reason: "O sesiune intraday este deja activă în GitHub Actions.",
          run_id: activeRun.id,
        });
      }
    }

    // 2. Pornim lanțul autonom de sesiuni de 15 minute (mode: session)
    const dispatchRes = await fetch(
      `https://api.github.com/repos/${repo}/actions/workflows/intraday_paper.yml/dispatches`,
      {
        method: "POST",
        headers,
        body: JSON.stringify({
          ref: "main",
          inputs: { mode: "session" },
        }),
        cache: "no-store",
      }
    );

    if (dispatchRes.status === 204 || dispatchRes.ok) {
      return NextResponse.json({
        ok: true,
        skipped: false,
        message: "Sesiunea intraday (lanțul de ștafetă 15m) a fost pornită automat în GitHub Actions.",
      });
    }

    return NextResponse.json(
      {
        ok: false,
        error: `GitHub Actions a returnat HTTP ${dispatchRes.status} la pornirea intraday_paper.yml.`,
      },
      { status: 502 }
    );
  } catch (err) {
    return NextResponse.json(
      {
        ok: false,
        error: `Eroare la apelul GitHub Actions: ${err instanceof Error ? err.message : "unknown"}`,
      },
      { status: 502 }
    );
  }
}

export async function GET() {
  return triggerIntradaySession();
}

export async function POST() {
  return triggerIntradaySession();
}
