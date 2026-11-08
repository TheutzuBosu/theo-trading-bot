import { NextResponse } from "next/server";
import { isAuthenticated } from "@/lib/auth";

export async function POST() {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "Neautorizat." }, { status: 401 });
  }

  const ghToken = process.env.GH_DISPATCH_TOKEN || "";
  const repo = process.env.GITHUB_REPO || "TheutzuBosu/theo-trading-bot";
  const alpacaKey = (process.env.ALPACA_API_KEY || "").trim();
  const alpacaSecret = (process.env.ALPACA_SECRET_KEY || "").trim();
  const alpacaBase = (process.env.ALPACA_BASE_URL || "https://paper-api.alpaca.markets").replace(
    /\/$/,
    ""
  );

  // 1. Direct instant liquidation on Alpaca Paper if credentials are present
  let alpacaLiquidated = false;
  if (alpacaKey && alpacaSecret) {
    try {
      const headers = {
        "APCA-API-KEY-ID": alpacaKey,
        "APCA-API-SECRET-KEY": alpacaSecret,
      };
      await fetch(`${alpacaBase}/v2/orders`, { method: "DELETE", headers, cache: "no-store" });
      const posDel = await fetch(`${alpacaBase}/v2/positions?cancel_orders=true`, {
        method: "DELETE",
        headers,
        cache: "no-store",
      });
      alpacaLiquidated = posDel.ok || posDel.status === 207 || posDel.status === 204;
    } catch {
      alpacaLiquidated = false;
    }
  }

  if (!ghToken && !alpacaLiquidated) {
    return NextResponse.json(
      {
        ok: false,
        message: "Lipsește GH_DISPATCH_TOKEN în variabilele Vercel pentru declanșarea kill.yml.",
      },
      { status: 500 }
    );
  }

  try {
    const res = ghToken
      ? await fetch(`https://api.github.com/repos/${repo}/actions/workflows/kill.yml/dispatches`, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${ghToken}`,
            Accept: "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ ref: "main" }),
        })
      : null;

    if ((res && (res.status === 204 || res.ok)) || alpacaLiquidated) {
      return NextResponse.json({
        ok: true,
        message:
          "Comanda KILL a fost executată! Toate ordinele și pozițiile deschise pe Alpaca Paper se închid la piață.",
      });
    }

    return NextResponse.json(
      {
        ok: false,
        message: `GitHub Actions a returnat HTTP ${res ? res.status : 500} la declanșarea kill.yml.`,
      },
      { status: 502 }
    );
  } catch {
    if (alpacaLiquidated) {
      return NextResponse.json({
        ok: true,
        message: "Pozițiile Alpaca au fost lichidate direct cu succes!",
      });
    }
    return NextResponse.json(
      {
        ok: false,
        message: "Eroare de rețea la trimiterea comenzii KILL către GitHub Actions.",
      },
      { status: 502 }
    );
  }
}
