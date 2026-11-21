import type { Company, Data, Deal, FinRow } from "./types";

export type Index = {
  data: Data;
  byId: Record<string, Company>;
  dealById: Record<string, Deal>;
  layerIndex: Record<string, number>;
  months: string[]; // YYYY-MM from start to covered_until
};

// When a deal happened, to the month. Undated deals count from when we first saw them.
export function dealMonth(d: Deal, start: string): string {
  if (d.date && /^\d{4}-\d{2}/.test(d.date)) return d.date.slice(0, 7);
  if (d.first_seen && /^\d{4}-\d{2}/.test(d.first_seen)) return d.first_seen.slice(0, 7);
  return start;
}

export function buildIndex(data: Data): Index {
  const start = (data.start || "2024-11-01").slice(0, 7);
  const end = (data.covered_until || new Date().toISOString()).slice(0, 7);
  // The timeline starts where news coverage starts; older deals show from the first step.
  const months: string[] = [];
  let [y, m] = start.split("-").map(Number);
  for (;;) {
    const key = `${y}-${String(m).padStart(2, "0")}`;
    months.push(key);
    if (key >= end) break;
    m++;
    if (m > 12) { m = 1; y++; }
  }
  return {
    data,
    byId: Object.fromEntries(data.companies.map(c => [c.id, c])),
    dealById: Object.fromEntries(data.deals.map(d => [d.id, d])),
    layerIndex: Object.fromEntries(data.layers.map((l, i) => [l.id, i])),
    months,
  };
}

export const monthLabel = (ym: string) =>
  new Date(ym + "-15T00:00:00").toLocaleDateString("en-US", { month: "short", year: "numeric" });

export function dateLabel(s: string | null): string {
  if (!s) return "Undated";
  if (/^\d{4}-\d{2}-\d{2}/.test(s))
    return new Date(s.slice(0, 10) + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  if (/^\d{4}-\d{2}$/.test(s)) return monthLabel(s);
  return s;
}

// ---- money, for SEC financials only (official filings) ----
const CUR: Record<string, string> = { USD: "$", EUR: "€", JPY: "¥", GBP: "£" };
export function money(v: number | undefined | null, cur: string | null): string {
  if (v == null) return "—";
  const a = Math.abs(v), sign = v < 0 ? "−" : "";
  const s = a >= 1e12 ? (a / 1e12).toFixed(2) + "T" : a >= 1e9 ? (a / 1e9).toFixed(a >= 1e11 ? 0 : 1) + "B"
    : a >= 1e6 ? (a / 1e6).toFixed(a >= 1e8 ? 0 : 1) + "M" : a.toLocaleString();
  return sign + (cur && CUR[cur] ? CUR[cur] : cur ? cur + " " : "") + s;
}
export const curSymbol = (cur: string | null) => (cur && CUR[cur]) || "";

const days = (a: string, b: string) => (Date.parse(b) - Date.parse(a)) / 864e5;

// Sum of four back-to-back quarters starting at `from`, or null.
export function ttm(q: FinRow[], key: keyof FinRow, from = 0): number | null {
  const r = q.slice(from, from + 4);
  if (r.length < 4 || r.some(x => x[key] == null)) return null;
  const span = days(r[3].end, r[0].end);
  return span > 250 && span < 300 ? r.reduce((a, x) => a + (x[key] as number), 0) : null;
}

// Calendar quarter the fiscal quarter mostly falls in (Nvidia's quarter to 25 Jan is Q4).
export function quarterLabel(end: string): string {
  const d = new Date(Date.parse(end + "T00:00:00") - 45 * 864e5);
  return `Q${Math.floor(d.getMonth() / 3) + 1} '${String(d.getFullYear()).slice(2)}`;
}

export function pctChange(now?: number | null, before?: number | null): number | null {
  if (now == null || before == null || before === 0) return null;
  if ((before < 0) !== (now < 0)) return null;
  return ((now - before) / Math.abs(before)) * 100;
}
