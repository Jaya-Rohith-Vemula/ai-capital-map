import { curSymbol, dateLabel, money, pctChange, quarterLabel, ttm } from "../data";
import type { Fin } from "../types";

function Change({ now, before }: { now?: number | null; before?: number | null }) {
  const p = pctChange(now, before);
  if (p == null) return <td className="chg" />;
  return <td className={"chg " + (p >= 0 ? "up" : "down")}>{p >= 0 ? "+" : "−"}{Math.abs(p).toFixed(0)}%</td>;
}

export default function Financials({ fin, asOf }: { fin: Fin; asOf: string | null }) {
  const [y, p] = [fin.annual[0], fin.annual[1]];
  const cur = fin.currency;
  const q = fin.quarterly;
  const capT = ttm(q, "capex"), capT0 = ttm(q, "capex", 4);
  const bars = q.filter(r => r.capex != null).slice(0, 12).reverse();
  const max = Math.max(1, ...bars.map(r => r.capex as number));
  const stale = y && asOf && (Date.parse(asOf) - Date.parse(y.end)) / 864e5 > 480;
  const fyLabel = y ? new Date(y.end + "T00:00:00").toLocaleDateString("en-US", { month: "short", year: "numeric" }) : "";

  return (
    <section>
      <h2>Financials <span className="count">SEC filings</span></h2>
      {y ? (
        <table className="fin">
          <thead><tr><th>Fiscal year to {fyLabel}{cur && cur !== "USD" ? ` · ${cur}` : ""}</th><th /><th className="chg">vs prior</th></tr></thead>
          <tbody>
            <tr><th>Revenue</th><td>{money(y.revenue, cur)}</td><Change now={y.revenue} before={p?.revenue} /></tr>
            <tr><th>Net income</th><td>{money(y.net_income, cur)}</td><Change now={y.net_income} before={p?.net_income} /></tr>
            <tr><th>Diluted EPS</th><td>{y.eps == null ? "—" : curSymbol(cur) + y.eps.toFixed(2)}</td><Change now={y.eps} before={p?.eps} /></tr>
            <tr><th>Capital spending</th><td>{money(y.capex, cur)}</td><Change now={y.capex} before={p?.capex} /></tr>
            <tr><th>Operating cash flow</th><td>{money(y.ocf, cur)}</td><Change now={y.ocf} before={p?.ocf} /></tr>
            {capT != null && <tr className="sep"><th>Capex, last 4 quarters</th><td>{money(capT, cur)}</td><Change now={capT} before={capT0} /></tr>}
          </tbody>
        </table>
      ) : <p className="empty">No full fiscal year filed yet.</p>}

      {bars.length >= 3 && (
        <figure className="bars" aria-label="Capital spending by quarter">
          <div className="bars-plot">
            {bars.map((r, i) => (
              <div key={r.end} className="qbar" title={`${quarterLabel(r.end)} (to ${r.end}): ${money(r.capex, cur)}`}>
                <i style={{ height: `${Math.max(2, ((r.capex as number) / max) * 100)}%`, ["--i" as string]: i }} />
              </div>
            ))}
          </div>
          <figcaption><span>{quarterLabel(bars[0].end)}</span><span>Capital spending by quarter</span><span>{quarterLabel(bars[bars.length - 1].end)}</span></figcaption>
        </figure>
      )}
      {stale && <p className="note warn">The latest figures SEC publishes in machine-readable form are for the year to {fyLabel}.</p>}
      <p className="note">As filed, latest {dateLabel(fin.last_filed)}. Capital spending is cash paid for property and equipment.{" "}
        <a href={`https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=${fin.cik}&type=10-&dateb=&owner=include&count=40`} target="_blank" rel="noopener noreferrer">Filings on EDGAR ↗</a></p>
    </section>
  );
}
