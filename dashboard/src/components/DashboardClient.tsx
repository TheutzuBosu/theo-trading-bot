"use client";

import React from "react";
import { useRouter } from "next/navigation";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { DashboardData, TradeRecord } from "@/lib/state";

function fmtUsd(value: number, signed = false): string {
  const sign = signed && value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${Math.abs(value).toFixed(2).replace(".", ",")} $`;
}

function fmtPct(value: number, signed = false): string {
  const sign = signed && value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${Math.abs(value).toFixed(2).replace(".", ",")}%`;
}

function fmtR(value: number): string {
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${Math.abs(value).toFixed(2).replace(".", ",")} R`;
}

function translateExitReason(reason: string, partialExit: boolean): string {
  if (reason === "stop") {
    return "Oprit la pragul de protecție (stop-loss atins).";
  }
  if (reason === "target") {
    return partialExit
      ? "Țintă de profit atinsă pe prima jumătate (VWAP & Ladder), restul închis pe revenirea la VWAP."
      : "Țintă de profit atinsă.";
  }
  if (reason === "eod") {
    return "Închis automat la finalul sesiunii (15:59 ET — fără poziții lăsate peste noapte).";
  }
  return reason;
}

function tradeTitle(t: TradeRecord): string {
  const act = t.direction === "long" ? "Am cumpărat" : "Am vândut scurt";
  const dirLabel = t.direction === "long" ? "LONG" : "SHORT";
  return `${act} ${t.symbol} (${dirLabel})`;
}

export default function DashboardClient({ data }: { data: DashboardData }) {
  const router = useRouter();
  const { summary, equity, trades } = data;

  async function handleLogout() {
    await fetch("/api/logout", { method: "POST" });
    router.refresh();
  }

  const totalPositive = summary.total_pnl >= 0;
  const todayPositive = summary.today_pnl >= 0;

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 pb-12">
      {/* Banner vizibil pentru date de exemplu */}
      {summary.is_sample && (
        <div className="bg-amber-500/15 border-b border-amber-500/40 px-4 py-2.5 text-center">
          <span className="inline-flex items-center gap-2 text-xs sm:text-sm font-medium text-amber-200">
            <span className="inline-block w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
            <strong>DATE DE EXEMPLU</strong> — Demo-ul live se conectează în etapa B6.
            Cifrele de mai jos provin din{" "}
            <code className="text-amber-100 bg-amber-950/60 px-1.5 py-0.5 rounded">
              tests/fixtures/state/
            </code>
            .
          </span>
        </div>
      )}

      <div className="max-w-5xl mx-auto px-4 pt-5 space-y-6">
        {/* 1. Bara de sus */}
        <header className="bg-slate-900 border border-slate-800 rounded-2xl p-4 sm:p-5 shadow-lg">
          <div className="flex flex-wrap items-center justify-between gap-3 pb-4 border-b border-slate-800">
            <div className="flex flex-wrap items-center gap-2.5">
              <span className="text-base sm:text-lg font-bold text-white">
                Theo Trading Bot
              </span>
              <span className="text-xs font-bold uppercase tracking-wider px-2.5 py-1 rounded-full bg-sky-500/20 text-sky-300 border border-sky-500/40">
                {summary.mode} · CONT DEMO
              </span>
              {summary.is_sample && (
                <span className="text-xs font-semibold uppercase tracking-wider px-2.5 py-1 rounded-full bg-amber-500/20 text-amber-300 border border-amber-500/40">
                  Date de exemplu
                </span>
              )}
            </div>

            <div className="flex items-center gap-2.5">
              <button
                type="button"
                disabled
                title="Butonul de oprire de urgență se conectează în etapa B6, când pornește procesul live pe demo."
                className="px-3.5 py-2 rounded-xl bg-rose-600/30 border border-rose-500/40 text-rose-200 text-xs font-bold uppercase tracking-wide cursor-not-allowed opacity-75"
              >
                KILL (se conectează în B6)
              </button>
              <button
                type="button"
                onClick={handleLogout}
                className="px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium transition"
              >
                Ieșire
              </button>
            </div>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-4">
            <div className="bg-slate-950/70 border border-slate-800/80 rounded-xl p-3.5">
              <div className="text-xs text-slate-400">Capital curent</div>
              <div className="text-lg sm:text-xl font-bold text-white mt-0.5">
                {fmtUsd(summary.equity)}
              </div>
              <div className="text-xs text-slate-500 mt-0.5">
                Start: {fmtUsd(summary.initial_capital)}
              </div>
            </div>

            <div className="bg-slate-950/70 border border-slate-800/80 rounded-xl p-3.5">
              <div className="text-xs text-slate-400">Profit total</div>
              <div
                className={`text-lg sm:text-xl font-bold mt-0.5 ${
                  totalPositive ? "text-emerald-400" : "text-rose-400"
                }`}
              >
                {fmtUsd(summary.total_pnl, true)}
              </div>
              <div
                className={`text-xs mt-0.5 ${
                  totalPositive ? "text-emerald-500" : "text-rose-500"
                }`}
              >
                {fmtPct(summary.total_pnl_pct, true)}
              </div>
            </div>

            <div className="bg-slate-950/70 border border-slate-800/80 rounded-xl p-3.5">
              <div className="text-xs text-slate-400">Profit azi</div>
              <div
                className={`text-lg sm:text-xl font-bold mt-0.5 ${
                  todayPositive ? "text-emerald-400" : "text-rose-400"
                }`}
              >
                {fmtUsd(summary.today_pnl, true)}
              </div>
              <div
                className={`text-xs mt-0.5 ${
                  todayPositive ? "text-emerald-500" : "text-rose-500"
                }`}
              >
                {fmtPct(summary.today_pnl_pct, true)}
              </div>
            </div>

            <div className="bg-slate-950/70 border border-slate-800/80 rounded-xl p-3.5">
              <div className="text-xs text-slate-400">Scădere de la vârf (Drawdown)</div>
              <div className="text-lg sm:text-xl font-bold text-slate-200 mt-0.5">
                {fmtPct(summary.current_drawdown_pct)}
              </div>
              <div className="text-xs text-slate-500 mt-0.5">
                Maximă: {fmtPct(summary.max_drawdown_pct)} (limită −15%)
              </div>
            </div>
          </div>
        </header>

        {/* 2. Graficul capitalului vs SPY cumpărat și ținut */}
        <section className="bg-slate-900 border border-slate-800 rounded-2xl p-4 sm:p-5 shadow-lg">
          <div className="flex flex-wrap items-baseline justify-between gap-2 mb-4">
            <div>
              <h2 className="text-base font-bold text-white">
                Evoluția capitalului față de S&amp;P 500 (SPY cumpărat și ținut)
              </h2>
              <p className="text-xs text-slate-400">
                Comparație directă: 500 $ în bot față de 500 $ lăsați în acțiuni SPY de la start.
              </p>
            </div>
          </div>

          <div className="h-64 sm:h-72 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={equity}
                margin={{ top: 8, right: 12, left: 0, bottom: 4 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis
                  dataKey="date"
                  stroke="#94a3b8"
                  fontSize={12}
                  tickMargin={8}
                />
                <YAxis
                  stroke="#94a3b8"
                  fontSize={12}
                  domain={["auto", "auto"]}
                  tickFormatter={(v) => `${v}$`}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#0f172a",
                    borderColor: "#334155",
                    borderRadius: "0.75rem",
                    fontSize: "12px",
                  }}
                  formatter={(value: number, name: string) => [
                    fmtUsd(Number(value)),
                    name,
                  ]}
                />
                <Legend wrapperStyle={{ fontSize: "12px" }} />
                <Line
                  type="monotone"
                  dataKey="bot_equity"
                  name="Bot (Paper)"
                  stroke="#10b981"
                  strokeWidth={2.5}
                  dot={{ r: 3 }}
                />
                <Line
                  type="monotone"
                  dataKey="spy_buy_hold"
                  name="SPY cumpărat și ținut"
                  stroke="#64748b"
                  strokeWidth={2}
                  strokeDasharray="5 5"
                  dot={{ r: 3 }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </section>

        {/* 3. Poziții deschise */}
        <section className="bg-slate-900 border border-slate-800 rounded-2xl p-4 sm:p-5 shadow-lg">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-base font-bold text-white">
              Poziții deschise acum ({summary.positions.length})
            </h2>
            <span className="text-xs text-slate-400">
              Toate pozițiile se închid automat înainte de 16:00 ET
            </span>
          </div>

          {summary.positions.length === 0 ? (
            <p className="text-sm text-slate-400 bg-slate-950/60 border border-slate-800/80 rounded-xl p-4">
              Nicio poziție deschisă în acest moment.
            </p>
          ) : (
            <div className="space-y-3">
              {summary.positions.map((pos, idx) => {
                const posPositive = pos.unrealized_pnl >= 0;
                return (
                  <div
                    key={`${pos.symbol}-${idx}`}
                    className="bg-slate-950/70 border border-slate-800 rounded-xl p-4"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="text-base font-bold text-white">
                          {pos.symbol}
                        </span>
                        <span className="text-xs font-semibold uppercase px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                          {pos.direction.toUpperCase()}
                        </span>
                        <span className="text-xs text-slate-400">
                          din {pos.entry_time} · {pos.qty} acțiuni
                        </span>
                      </div>

                      <div
                        className={`text-sm font-bold ${
                          posPositive ? "text-emerald-400" : "text-rose-400"
                        }`}
                      >
                        {fmtUsd(pos.unrealized_pnl, true)} ({fmtR(pos.unrealized_r)})
                      </div>
                    </div>

                    <div className="grid grid-cols-3 gap-2 text-xs text-slate-300 mt-3 pt-3 border-t border-slate-800/80">
                      <div>
                        <span className="text-slate-500 block">Preț intrare</span>
                        {fmtUsd(pos.entry_price)}
                      </div>
                      <div>
                        <span className="text-slate-500 block">Preț curent</span>
                        {fmtUsd(pos.current_price)}
                      </div>
                      <div>
                        <span className="text-slate-500 block">Stop-loss activ</span>
                        <span className="text-amber-300 font-medium">
                          {fmtUsd(pos.stop)}
                        </span>
                      </div>
                    </div>

                    <p className="text-xs text-slate-400 mt-2.5">
                      <strong className="text-slate-300">De ce a intrat:</strong>{" "}
                      {pos.entry_reason}
                    </p>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {/* 4. Jurnalul de tranzacții */}
        <section className="bg-slate-900 border border-slate-800 rounded-2xl p-4 sm:p-5 shadow-lg">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-base font-bold text-white">
                Jurnalul de tranzacții ({trades.length})
              </h2>
              <p className="text-xs text-slate-400">
                Cele mai noi sus · Fiecare decizie arată regula exactă de intrare și de ieșire
              </p>
            </div>
          </div>

          <div className="space-y-3.5">
            {trades.map((t, idx) => {
              const win = t.pnl >= 0;
              return (
                <article
                  key={`${t.symbol}-${t.entry_time}-${idx}`}
                  className="bg-slate-950/70 border border-slate-800 rounded-xl p-4 space-y-2.5"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span
                        className={`inline-block w-2.5 h-2.5 rounded-full ${
                          win ? "bg-emerald-400" : "bg-rose-400"
                        }`}
                      />
                      <h3 className="text-sm sm:text-base font-bold text-white">
                        {tradeTitle(t)}
                      </h3>
                    </div>

                    <div
                      className={`text-sm sm:text-base font-bold px-2.5 py-1 rounded-lg border ${
                        win
                          ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
                          : "bg-rose-500/15 text-rose-300 border-rose-500/30"
                      }`}
                    >
                      {fmtUsd(t.pnl, true)} ({fmtR(t.r_multiple)})
                    </div>
                  </div>

                  <div className="text-xs text-slate-400 flex flex-wrap gap-x-4 gap-y-1">
                    <span>
                      Intrare: <strong className="text-slate-200">{t.entry_time}</strong> la{" "}
                      {fmtUsd(t.entry_price)}
                    </span>
                    <span>
                      Ieșire: <strong className="text-slate-200">{t.exit_time}</strong> la{" "}
                      {fmtUsd(t.exit_price)}
                    </span>
                    <span>
                      Cantitate: <strong className="text-slate-200">{t.qty}</strong> acțiuni
                    </span>
                    <span>
                      Stop inițial: <strong className="text-slate-200">{fmtUsd(t.initial_stop)}</strong>{" "}
                      (risc {fmtPct(t.risk_pct * 100)})
                    </span>
                  </div>

                  <div className="text-xs sm:text-sm space-y-1.5 pt-2 border-t border-slate-800/80">
                    <p className="text-slate-200">
                      <strong className="text-sky-300">De ce a intrat:</strong>{" "}
                      {t.entry_reason}
                    </p>
                    <p className="text-slate-300">
                      <strong className="text-amber-300">De ce a ieșit:</strong>{" "}
                      {translateExitReason(t.exit_reason, t.partial_exit)}
                    </p>
                  </div>
                </article>
              );
            })}
          </div>
        </section>
      </div>
    </div>
  );
}
