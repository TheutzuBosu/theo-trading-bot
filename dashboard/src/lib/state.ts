import fs from "fs";
import path from "path";

export interface OpenPosition {
  symbol: string;
  direction: string;
  entry_time: string;
  qty: number;
  entry_price: number;
  current_price: number;
  stop: number;
  initial_stop: number;
  unrealized_pnl: number;
  unrealized_r: number;
  entry_reason: string;
}

export interface PremarketQuote {
  price: number;
  prev_close: number;
  gap_pct: number;
}

export interface StockOpportunity {
  symbol: string;
  action: string;
  direction: string;
  price: number;
  change_pct?: number;
  gap_pct?: number;
  stop_price: number;
  target_price: number;
  rr_ratio: number;
  stake_dollars: number;
  confidence: number;
  catalyst?: string;
  reason_ro: string;
}

export interface PremarketBriefing {
  updated_at: string;
  risk_regime: string;
  quotes: Record<string, PremarketQuote>;
  explanation_ro: string;
  headlines: string[];
  earnings_today: Array<{ symbol: string; hour?: string }>;
  opportunities?: StockOpportunity[];
  top_movers?: Array<{ symbol: string; price: number; change_pct: number }>;
}

export interface WeekendKeyEvent {
  day: string;
  event: string;
  impact: "HIGH" | "MEDIUM" | "LOW" | string;
}

export interface WeekendWatchlistItem {
  symbol: string;
  direction: string;
  thesis_ro: string;
}

export interface WeekendBriefing {
  updated_at: string;
  period: string;
  executive_summary_ro: string;
  weekly_performance?: {
    total_trades: number;
    win_rate_pct: number;
    total_pnl: number;
    best_trade: string;
    worst_trade: string;
  };
  lessons_learned?: string[];
  macro_outlook_ro?: string;
  key_events?: WeekendKeyEvent[];
  tactical_plan_ro?: string;
  watchlist?: WeekendWatchlistItem[];
}

export interface StateSummary {
  mode: "PAPER" | "LIVE";
  is_sample: boolean;
  initial_capital: number;
  equity: number;
  total_pnl: number;
  total_pnl_pct: number;
  today_pnl: number;
  today_pnl_pct: number;
  current_drawdown_pct: number;
  max_drawdown_pct: number;
  updated_at: string;
  positions: OpenPosition[];
  premarket?: PremarketBriefing;
  weekend_briefing?: WeekendBriefing;
}

export interface EquityPoint {
  date: string;
  bot_equity: number;
  spy_buy_hold: number;
  daily_pnl: number;
  drawdown_pct: number;
}

export interface TradeRecord {
  symbol: string;
  direction: string;
  signal_time: string;
  entry_time: string;
  entry_open: number;
  entry_price: number;
  exit_time: string;
  exit_raw: number;
  exit_price: number;
  qty: number;
  initial_stop: number;
  stop: number;
  target: number | null;
  initial_risk: number;
  risk_pct: number;
  notional_pct: number;
  pnl: number;
  r_multiple: number;
  mae_r: number;
  mfe_r: number;
  bars_held: number;
  equity_at_entry: number;
  exit_reason: string;
  exit_at_open: boolean;
  partial_exit: boolean;
  entry_reason: string;
  entry_bar: number;
  exit_bar: number;
}

export interface DashboardData {
  summary: StateSummary;
  equity: EquityPoint[];
  trades: TradeRecord[];
}

const FALLBACK_SUMMARY: StateSummary = {
  mode: "PAPER",
  is_sample: true,
  initial_capital: 500.0,
  equity: 510.12,
  total_pnl: 10.12,
  total_pnl_pct: 2.02,
  today_pnl: 2.64,
  today_pnl_pct: 0.52,
  current_drawdown_pct: 0.0,
  max_drawdown_pct: -0.48,
  updated_at: "2026-11-03T16:00:00-05:00",
  positions: [
    {
      symbol: "SPY",
      direction: "long",
      entry_time: "2026-11-03 10:01:00-05:00",
      qty: 0.86,
      entry_price: 585.015,
      current_price: 586.9,
      stop: 584.2,
      initial_stop: 582.1,
      unrealized_pnl: 1.62,
      unrealized_r: 0.65,
      entry_reason:
        "D1: prețul SPY a ieșit deasupra benzii de zgomot de 14 zile la 10:00 ET.",
    },
  ],
};

const FALLBACK_EQUITY_CSV = `date,bot_equity,spy_buy_hold,daily_pnl,drawdown_pct
2026-10-27,500.00,500.00,0.00,0.00
2026-10-28,502.44,501.35,2.44,0.00
2026-10-29,500.01,499.80,-2.43,-0.48
2026-10-30,503.81,501.90,3.80,0.00
2026-10-31,507.48,503.10,3.67,0.00
2026-11-03,510.12,504.25,2.64,0.00`;

const FALLBACK_TRADES_CSV = `symbol,direction,signal_time,entry_time,entry_open,entry_price,exit_time,exit_raw,exit_price,qty,initial_stop,stop,target,initial_risk,risk_pct,notional_pct,pnl,r_multiple,mae_r,mfe_r,bars_held,equity_at_entry,exit_reason,exit_at_open,partial_exit,entry_reason,entry_bar,exit_bar
SPY,long,2026-10-28 10:00:00-04:00,2026-10-28 10:01:00-04:00,581.20,581.215,2026-10-28 15:59:00-04:00,584.10,584.085,0.85,578.30,582.40,,2.915,0.005,0.988,2.44,0.98,-0.25,1.35,358,500.00,eod,False,False,"D1: prețul SPY (581,20 $) a ieșit deasupra benzii de zgomot de 14 zile (580,45 $) la verificarea de la 10:00 ET, cu VWAP la 579,90 $.",31,389
QQQ,long,2026-10-29 10:30:00-04:00,2026-10-29 10:31:00-04:00,498.50,498.515,2026-10-29 12:14:00-04:00,496.10,496.085,1.00,496.10,496.10,,2.415,0.0048,0.992,-2.43,-1.01,-1.01,0.42,103,502.44,stop,False,False,"D1: prețul QQQ (498,50 $) a depășit banda superioară de zgomot (497,80 $) la 10:30 ET; stop inițial pus pe VWAP (496,10 $).",61,164
SPY,long,2026-10-30 10:00:00-04:00,2026-10-30 10:01:00-04:00,583.40,583.415,2026-10-30 14:22:00-04:00,587.90,587.885,0.85,580.50,585.20,587.90,2.915,0.005,0.992,3.80,1.53,-0.18,1.60,261,500.01,target,False,True,"D1b: ieșire din banda de zgomot la 10:00 ET (583,40 $ > 582,60 $); țintă de profit atinsă și restul închis pe revenirea la VWAP.",31,292
QQQ,long,2026-10-31 11:00:00-04:00,2026-10-31 11:01:00-04:00,501.10,501.115,2026-10-31 15:59:00-04:00,504.80,504.785,1.00,498.60,503.10,,2.515,0.005,0.995,3.67,1.46,-0.12,1.68,298,503.81,eod,False,False,"D1: spargere deasupra benzii de zgomot la 11:00 ET (501,10 $ > 500,25 $), trend susținut peste VWAP până la închiderea sesiunii.",91,389
SPY,long,2026-11-03 10:00:00-05:00,2026-11-03 10:01:00-05:00,585.00,585.015,2026-11-03 15:59:00-05:00,588.10,588.085,0.86,582.10,586.50,,2.915,0.0049,0.991,2.64,1.05,-0.20,1.22,358,507.48,eod,False,False,"D1: prețul SPY a ieșit din banda de zgomot la 10:00 ET (585,00 $ > 584,10 $); poziție închisă automat la 15:59 ET.",31,389`;

export function parseCsvLine(line: string): string[] {
  const fields: string[] = [];
  let current = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') {
      if (inQuotes && line[i + 1] === '"') {
        current += '"';
        i++;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (ch === "," && !inQuotes) {
      fields.push(current);
      current = "";
    } else {
      current += ch;
    }
  }
  fields.push(current);
  return fields;
}

export function parseCsv(raw: string): Record<string, string>[] {
  const lines = raw
    .trim()
    .split(/\r?\n/)
    .filter((l) => l.trim().length > 0);
  if (lines.length < 2) return [];
  const headers = parseCsvLine(lines[0]);
  return lines.slice(1).map((line) => {
    const values = parseCsvLine(line);
    const row: Record<string, string> = {};
    headers.forEach((h, idx) => {
      row[h] = values[idx] ?? "";
    });
    return row;
  });
}

function parseEquityCsv(raw: string): EquityPoint[] {
  return parseCsv(raw).map((r) => ({
    date: r.date,
    bot_equity: Number(r.bot_equity),
    spy_buy_hold: Number(r.spy_buy_hold),
    daily_pnl: Number(r.daily_pnl),
    drawdown_pct: Number(r.drawdown_pct),
  }));
}

function parseTradesCsv(raw: string): TradeRecord[] {
  const rows = parseCsv(raw).map((r) => ({
    symbol: r.symbol,
    direction: r.direction,
    signal_time: r.signal_time,
    entry_time: r.entry_time,
    entry_open: Number(r.entry_open),
    entry_price: Number(r.entry_price),
    exit_time: r.exit_time,
    exit_raw: Number(r.exit_raw),
    exit_price: Number(r.exit_price),
    qty: Number(r.qty),
    initial_stop: Number(r.initial_stop),
    stop: Number(r.stop),
    target: r.target ? Number(r.target) : null,
    initial_risk: Number(r.initial_risk),
    risk_pct: Number(r.risk_pct),
    notional_pct: Number(r.notional_pct),
    pnl: Number(r.pnl),
    r_multiple: Number(r.r_multiple),
    mae_r: Number(r.mae_r),
    mfe_r: Number(r.mfe_r),
    bars_held: Number(r.bars_held),
    equity_at_entry: Number(r.equity_at_entry),
    exit_reason: r.exit_reason,
    exit_at_open: r.exit_at_open.toLowerCase() === "true",
    partial_exit: r.partial_exit.toLowerCase() === "true",
    entry_reason: r.entry_reason,
    entry_bar: Number(r.entry_bar),
    exit_bar: Number(r.exit_bar),
  }));
  // Most recent trade first
  return rows.reverse();
}

async function fetchGithubFile(filePath: string, token: string): Promise<string | null> {
  const repo = process.env.GITHUB_REPO || "TheutzuBosu/theo-trading-bot";
  const url = `https://api.github.com/repos/${repo}/contents/${filePath}?ref=state&_t=${Date.now()}`;
  try {
    const res = await fetch(url, {
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github.v3.raw",
        "Cache-Control": "no-cache",
      },
      cache: "no-store",
    });
    if (!res.ok) return null;
    return await res.text();
  } catch {
    return null;
  }
}

function readFixtureFile(filename: string): string | null {
  const candidates = [
    path.resolve(process.cwd(), "..", "tests", "fixtures", "state", filename),
    path.resolve(process.cwd(), "tests", "fixtures", "state", filename),
  ];
  for (const p of candidates) {
    if (fs.existsSync(p)) {
      return fs.readFileSync(p, "utf8");
    }
  }
  return null;
}

interface AlpacaAccountPayload {
  equity: string;
  last_equity: string;
  cash: string;
  buying_power: string;
}

interface AlpacaPositionPayload {
  symbol: string;
  qty: string;
  side: string;
  avg_entry_price: string;
  current_price: string;
  unrealized_pl: string;
}

async function fetchLiveAlpacaData(): Promise<{
  account: AlpacaAccountPayload;
  positions: AlpacaPositionPayload[];
} | null> {
  const apiKey = (process.env.ALPACA_API_KEY || "").trim();
  const secretKey = (process.env.ALPACA_SECRET_KEY || "").trim();
  const baseUrl = (process.env.ALPACA_BASE_URL || "https://paper-api.alpaca.markets").replace(
    /\/$/,
    ""
  );

  if (!apiKey || !secretKey) {
    return null;
  }

  try {
    const [accRes, posRes] = await Promise.all([
      fetch(`${baseUrl}/v2/account`, {
        headers: {
          "APCA-API-KEY-ID": apiKey,
          "APCA-API-SECRET-KEY": secretKey,
        },
        cache: "no-store",
      }),
      fetch(`${baseUrl}/v2/positions`, {
        headers: {
          "APCA-API-KEY-ID": apiKey,
          "APCA-API-SECRET-KEY": secretKey,
        },
        cache: "no-store",
      }),
    ]);

    if (!accRes.ok) return null;
    const account: AlpacaAccountPayload = await accRes.json();
    const positions: AlpacaPositionPayload[] = posRes.ok ? await posRes.json() : [];
    return { account, positions };
  } catch {
    return null;
  }
}

export async function loadDashboardData(): Promise<DashboardData> {
  let summary: StateSummary = FALLBACK_SUMMARY;
  let equity: EquityPoint[] = parseEquityCsv(FALLBACK_EQUITY_CSV);
  let trades: TradeRecord[] = parseTradesCsv(FALLBACK_TRADES_CSV);

  const ghToken = process.env.GH_DISPATCH_TOKEN || "";
  if (ghToken) {
    const [summaryRaw, equityRaw, tradesRaw] = await Promise.all([
      fetchGithubFile("state/summary.json", ghToken),
      fetchGithubFile("state/equity.csv", ghToken),
      fetchGithubFile("state/trades.csv", ghToken),
    ]);
    if (summaryRaw && equityRaw && tradesRaw) {
      summary = { ...JSON.parse(summaryRaw), is_sample: false };
      equity = parseEquityCsv(equityRaw);
      trades = parseTradesCsv(tradesRaw);
    }
  } else {
    const summaryRaw = readFixtureFile("summary.json");
    const equityRaw = readFixtureFile("equity.csv");
    const tradesRaw = readFixtureFile("trades.csv");
    if (summaryRaw) summary = JSON.parse(summaryRaw);
    if (equityRaw) equity = parseEquityCsv(equityRaw);
    if (tradesRaw) trades = parseTradesCsv(tradesRaw);
  }

  // Live direct Alpaca overlay: if Alpaca API credentials are configured on Vercel,
  // fetch live account balance and positions in real-time on every page refresh!
  const liveAlpaca = await fetchLiveAlpacaData();
  if (liveAlpaca && liveAlpaca.account) {
    const liveEq = parseFloat(liveAlpaca.account.equity);
    const lastEq = parseFloat(liveAlpaca.account.last_equity) || summary.initial_capital;
    if (!isNaN(liveEq) && liveEq > 0) {
      const initCap = summary.initial_capital || 500.0;
      const totalPnl = Math.round((liveEq - initCap) * 100) / 100;
      const totalPnlPct = Math.round((totalPnl / initCap) * 10000) / 100;
      const todayPnl = Math.round((liveEq - lastEq) * 100) / 100;
      const todayPnlPct = lastEq > 0 ? Math.round((todayPnl / lastEq) * 10000) / 100 : 0;

      summary.equity = Math.round(liveEq * 100) / 100;
      summary.total_pnl = totalPnl;
      summary.total_pnl_pct = totalPnlPct;
      summary.today_pnl = todayPnl;
      summary.today_pnl_pct = todayPnlPct;
      summary.updated_at = new Date().toISOString();

      // Synchronize positions live prices & unrealized PnL from Alpaca
      if (Array.isArray(liveAlpaca.positions)) {
        const livePosMap = new Map(liveAlpaca.positions.map((p) => [p.symbol.toUpperCase(), p]));
        const updatedPositions: OpenPosition[] = [];

        // 1. Update existing known positions (preserve entry_reason and stop-loss)
        for (const pos of summary.positions || []) {
          const liveP = livePosMap.get(pos.symbol.toUpperCase());
          if (liveP) {
            pos.current_price = Math.round(parseFloat(liveP.current_price) * 10000) / 10000;
            pos.unrealized_pnl = Math.round(parseFloat(liveP.unrealized_pl) * 100) / 100;
            pos.qty = Math.round(parseFloat(liveP.qty) * 10000) / 10000;
            updatedPositions.push(pos);
            livePosMap.delete(pos.symbol.toUpperCase());
          }
        }

        // 2. Add any live open positions from broker not yet in summary
        for (const [sym, lp] of livePosMap.entries()) {
          const entryPrice = parseFloat(lp.avg_entry_price) || 0;
          const currPrice = parseFloat(lp.current_price) || entryPrice;
          const unrPnl = parseFloat(lp.unrealized_pl) || 0;
          updatedPositions.push({
            symbol: sym,
            direction: lp.side === "short" ? "short" : "long",
            entry_time: new Date().toISOString(),
            qty: Math.round(parseFloat(lp.qty) * 10000) / 10000,
            entry_price: Math.round(entryPrice * 10000) / 10000,
            current_price: Math.round(currPrice * 10000) / 10000,
            stop: 0,
            initial_stop: 0,
            unrealized_pnl: Math.round(unrPnl * 100) / 100,
            unrealized_r: 0,
            entry_reason: "Poziție live preluată direct din contul Alpaca Paper.",
          });
        }

        summary.positions = updatedPositions;
      }
    }
  }

  return {
    summary,
    equity,
    trades,
  };
}
