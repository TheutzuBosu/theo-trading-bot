import { NextResponse } from "next/server";
import { isAuthenticated } from "@/lib/auth";

export async function POST() {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "Neautorizat." }, { status: 401 });
  }

  const ghToken = process.env.GH_DISPATCH_TOKEN || "";
  const repo = process.env.GITHUB_REPO || "TheutzuBosu/theo-trading-bot";

  if (!ghToken) {
    return NextResponse.json(
      {
        ok: false,
        message: "Lipsește GH_DISPATCH_TOKEN în variabilele Vercel pentru declanșarea kill.yml.",
      },
      { status: 500 }
    );
  }

  try {
    const res = await fetch(
      `https://api.github.com/repos/${repo}/actions/workflows/kill.yml/dispatches`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${ghToken}`,
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ ref: "main" }),
      }
    );

    if (res.status === 204 || res.ok) {
      return NextResponse.json({
        ok: true,
        message:
          "Comanda KILL a fost trimisă! Toate pozițiile deschise pe Alpaca Paper se închid la piață.",
      });
    }

    return NextResponse.json(
      {
        ok: false,
        message: `GitHub Actions a returnat HTTP ${res.status} la declanșarea kill.yml.`,
      },
      { status: 502 }
    );
  } catch {
    return NextResponse.json(
      {
        ok: false,
        message: "Eroare de rețea la trimiterea comenzii KILL către GitHub Actions.",
      },
      { status: 502 }
    );
  }
}
