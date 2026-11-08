import { NextResponse } from "next/server";
import { isAuthenticated } from "@/lib/auth";
import { dispatchSession, findActiveSessionRun } from "@/lib/github";

export const dynamic = "force-dynamic";

// Vercel Cron sends `Authorization: Bearer <CRON_SECRET>` when CRON_SECRET is set in the project.
// With the secret set, only that header or the logged-in owner may call this route (B6f: it was
// open to anyone). Until the owner adds CRON_SECRET, the Vercel cron user agent is still accepted
// so the morning start keeps working (the call only starts a deduplicated session).
async function isAllowed(req: Request): Promise<boolean> {
  const secret = (process.env.CRON_SECRET || "").trim();
  const header = req.headers.get("authorization") || "";
  if (secret && header === `Bearer ${secret}`) return true;
  if (!secret && (req.headers.get("user-agent") || "").startsWith("vercel-cron/")) return true;
  return isAuthenticated();
}

async function triggerIntradaySession(req: Request) {
  if (!(await isAllowed(req))) {
    return NextResponse.json({ ok: false, error: "Neautorizat." }, { status: 401 });
  }
  const ghToken = (process.env.GH_DISPATCH_TOKEN || "").trim();
  if (!ghToken) {
    return NextResponse.json(
      { ok: false, error: "Lipsește GH_DISPATCH_TOKEN în variabilele de mediu Vercel." },
      { status: 500 }
    );
  }

  try {
    // 1. No duplicate start while a run is active or waiting in the queue
    const activeRunId = await findActiveSessionRun(ghToken);
    if (activeRunId) {
      return NextResponse.json({
        ok: true,
        skipped: true,
        reason: "O sesiune intraday este deja activă sau în coadă în GitHub Actions.",
        run_id: activeRunId,
      });
    }

    // 2. Start the 15-minute relay chain (mode: session)
    const status = await dispatchSession(ghToken);
    if (status === 204) {
      return NextResponse.json({
        ok: true,
        skipped: false,
        message: "Sesiunea intraday (lanțul de ștafetă 15m) a fost pornită în GitHub Actions.",
      });
    }
    return NextResponse.json(
      { ok: false, error: `GitHub Actions a returnat HTTP ${status} la pornirea intraday_paper.yml.` },
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

export async function GET(req: Request) {
  return triggerIntradaySession(req);
}

export async function POST(req: Request) {
  return triggerIntradaySession(req);
}
