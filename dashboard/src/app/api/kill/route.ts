import { NextResponse } from "next/server";
import { isAuthenticated } from "@/lib/auth";
import { githubHeaders, repoName, writeKillSwitchFlag } from "@/lib/github";

export const dynamic = "force-dynamic";

// KILL (B6f): 1) set state/kill_switch.json = active directly, so the running bot stops opening
// trades within a minute; 2) close everything on Alpaca now; 3) start kill.yml (journal, Telegram).
// "ok" only when the bot was really told to stop (flag written or kill.yml started): closing the
// positions alone is not enough, the bot would reopen trades on its next cycle.
export async function POST() {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "Neautorizat." }, { status: 401 });
  }

  const ghToken = (process.env.GH_DISPATCH_TOKEN || "").trim();
  const alpacaKey = (process.env.ALPACA_API_KEY || "").trim();
  const alpacaSecret = (process.env.ALPACA_SECRET_KEY || "").trim();
  const alpacaBase = (process.env.ALPACA_BASE_URL || "https://paper-api.alpaca.markets").replace(
    /\/$/,
    ""
  );

  // 1. Stop flag for the bot
  const flagWritten = ghToken
    ? await writeKillSwitchFlag(ghToken, "KILL apăsat în Dashboard")
    : false;

  // 2. Immediate liquidation on Alpaca Paper
  let alpacaLiquidated = false;
  if (alpacaKey && alpacaSecret) {
    try {
      const headers = { "APCA-API-KEY-ID": alpacaKey, "APCA-API-SECRET-KEY": alpacaSecret };
      await fetch(`${alpacaBase}/v2/orders`, { method: "DELETE", headers, cache: "no-store" });
      const posDel = await fetch(`${alpacaBase}/v2/positions?cancel_orders=true`, {
        method: "DELETE",
        headers,
        cache: "no-store",
      });
      alpacaLiquidated = posDel.ok || posDel.status === 207;
    } catch {
      alpacaLiquidated = false;
    }
  }

  // 3. kill.yml: liquidation again from the bot + journal + Telegram alert
  let killDispatched = false;
  if (ghToken) {
    try {
      const res = await fetch(
        `https://api.github.com/repos/${repoName()}/actions/workflows/kill.yml/dispatches`,
        {
          method: "POST",
          headers: githubHeaders(ghToken),
          body: JSON.stringify({ ref: "main" }),
          cache: "no-store",
        }
      );
      killDispatched = res.status === 204;
    } catch {
      killDispatched = false;
    }
  }

  const details = { flag_written: flagWritten, alpaca_liquidated: alpacaLiquidated, kill_workflow: killDispatched };
  if (flagWritten || killDispatched) {
    return NextResponse.json({
      ok: true,
      ...details,
      message: alpacaLiquidated
        ? "KILL executat: botul e oprit și toate pozițiile Alpaca Paper se închid la piață."
        : "KILL trimis: botul e oprit; pozițiile se închid prin workflow-ul kill.yml în 1-2 minute.",
    });
  }
  return NextResponse.json(
    {
      ok: false,
      ...details,
      message: alpacaLiquidated
        ? "Pozițiile au fost închise, DAR botul nu a primit oprirea (GitHub indisponibil). Apasă din nou KILL."
        : "KILL a eșuat: nici GitHub, nici Alpaca nu au răspuns. Apasă din nou sau închide din aplicația Alpaca.",
    },
    { status: 502 }
  );
}
