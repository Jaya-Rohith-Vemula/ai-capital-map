import { useMemo } from "react";
import type { Index } from "../data";
import { dateLabel, money, ttm } from "../data";
import { EVIDENCE, LAYER_COLORS, STATUSES, TYPES, type Theme } from "../meta";
import type { Company, Deal } from "../types";
import Financials from "./Financials";

type Nav = { company: (id: string) => void; deal: (id: string) => void; about: () => void };
type Common = { index: Index; visible: Set<string>; theme: Theme; nav: Nav };

export function LayerTag({ index, layer, theme }: { index: Index; layer: string; theme: Theme }) {
  const i = index.layerIndex[layer] ?? 0;
  const c = LAYER_COLORS[theme][i % LAYER_COLORS[theme].length];
  return <span className="tag"><i className="dot" style={{ background: c }} />{index.data.layers[i]?.name}</span>;
}

export function TypeTag({ type, theme }: { type: string; theme: Theme }) {
  const t = TYPES[type];
  return <span className="tag"><i className="bar" style={{ background: t ? t[theme] : undefined }} />{t?.label || type}</span>;
}

function CompanyLink({ c, nav }: { c?: Company; nav: Nav }) {
  if (!c) return null;
  return <button className="link" onClick={() => nav.company(c.id)}>{c.name}</button>;
}

// ---------------------------------------------------------------- overview
export function Overview({ index, visible, theme, nav }: Common) {
  const { data, byId } = index;
  const deals = data.deals.filter(d => visible.has(d.id));

  const stats = useMemo(() => {
    const partners: Record<string, Set<string>> = {};
    const dir = new Set<string>();
    deals.forEach(d => {
      (partners[d.from] ??= new Set()).add(d.to);
      (partners[d.to] ??= new Set()).add(d.from);
      dir.add(d.from + ">" + d.to);
    });
    const connected = Object.entries(partners).sort((a, b) => b[1].size - a[1].size).slice(0, 7);
    const mutual: [string, string][] = [];
    dir.forEach(k => {
      const [a, b] = k.split(">");
      if (a < b && dir.has(b + ">" + a)) mutual.push([a, b]);
    });
    mutual.sort((x, y) => (partners[y[0]].size + partners[y[1]].size) - (partners[x[0]].size + partners[x[1]].size));
    const latest = [...deals].sort((a, b) => String(b.date || "").localeCompare(String(a.date || ""))).slice(0, 6);
    const capex = data.companies
      .map(c => [c, c.fin?.currency === "USD" ? ttm(c.fin.quarterly, "capex") : null] as const)
      .filter((r): r is readonly [Company, number] => r[1] != null)
      .sort((a, b) => b[1] - a[1]).slice(0, 6);
    return { connected, mutual: mutual.slice(0, 6), latest, capex, companies: Object.keys(partners).length, primary: deals.filter(d => d.evidence === "press release").length };
  }, [deals, data]);

  const maxCapex = stats.capex[0]?.[1] || 1;
  return (
    <div className="panel-body">
      <p className="kicker">The AI build-out</p>
      <h1 className="display">Who is building AI with whom</h1>
      <p className="lede">
        Every arrow is a deal reported between two companies: investments, compute contracts, chip orders, leases, power.
        It points from the one paying or investing to the one supplying. Click a company or an arrow to read more.
      </p>
      <dl className="figures">
        <div><dt>Companies</dt><dd>{stats.companies}</dd></div>
        <div><dt>Deals</dt><dd>{deals.length}</dd></div>
        <div><dt>From a press release</dt><dd>{stats.primary}</dd></div>
      </dl>

      <section>
        <h2>Most connected</h2>
        <ol className="rank">
          {stats.connected.map(([id, s]) => (
            <li key={id}><button className="row" onClick={() => nav.company(id)}>
              <span>{byId[id]?.name}</span><span className="meter"><i style={{ width: `${(s.size / stats.connected[0][1].size) * 100}%` }} /></span>
              <span className="num">{s.size}</span></button></li>
          ))}
        </ol>
        <p className="note">Distinct counterparties.</p>
      </section>

      {stats.mutual.length > 0 && <section>
        <h2>Deals in both directions</h2>
        <p className="note lead-in">Each side is both a customer and a supplier, or an investor and a customer, of the other.</p>
        <ul className="plain">
          {stats.mutual.map(([a, b]) => (
            <li key={a + b} className="pair">
              <CompanyLink c={byId[a]} nav={nav} /><span className="arrows" aria-label="both directions">⇄</span><CompanyLink c={byId[b]} nav={nav} />
            </li>
          ))}
        </ul>
      </section>}

      <section>
        <h2>Latest</h2>
        <ul className="plain">{stats.latest.map(d => <DealRow key={d.id} d={d} index={index} theme={theme} nav={nav} />)}</ul>
      </section>

      {stats.capex.length > 0 && <section>
        <h2>Capital spending, last four quarters</h2>
        <ol className="rank">
          {stats.capex.map(([c, v]) => (
            <li key={c.id}><button className="row" onClick={() => nav.company(c.id)}>
              <span>{c.name}</span><span className="meter"><i style={{ width: `${(v / maxCapex) * 100}%` }} /></span>
              <span className="num">{money(v, "USD")}</span></button></li>
          ))}
        </ol>
        <p className="note">From SEC filings: cash paid for property and equipment. US-dollar filers.</p>
      </section>}

      <p className="fineprint">
        Compiled from news reports and press releases; may contain errors. Not investment advice.{" "}
        <button className="link" onClick={nav.about}>How this is made</button>
      </p>
    </div>
  );
}

// ---------------------------------------------------------------- one deal row
function DealRow({ d, index, theme, nav, viewpoint }: { d: Deal; index: Index; theme: Theme; nav: Nav; viewpoint?: string }) {
  const other = viewpoint ? index.byId[d.from === viewpoint ? d.to : d.from] : null;
  return (
    <li>
      <button className="deal" onClick={() => nav.deal(d.id)}>
        <span className="deal-head">
          {other ? <b>{other.name}</b> : <b>{index.byId[d.from]?.name} <span className="to">→</span> {index.byId[d.to]?.name}</b>}
          <span className="date">{dateLabel(d.date)}</span>
        </span>
        <span className="deal-sum">{d.summary}</span>
        <span className="deal-tags"><TypeTag type={d.type} theme={theme} />
          {d.status && d.status !== "announced" && <span className={"tag status " + d.status}>{STATUSES[d.status]?.label}</span>}
        </span>
      </button>
    </li>
  );
}

// ---------------------------------------------------------------- company
export function CompanyPanel({ id, index, visible, theme, nav }: Common & { id: string }) {
  const c = index.byId[id];
  const mine = index.data.deals.filter(d => (d.from === id || d.to === id) && visible.has(d.id))
    .sort((a, b) => String(b.date || "").localeCompare(String(a.date || "")));
  const hidden = index.data.deals.filter(d => (d.from === id || d.to === id) && !visible.has(d.id)).length;
  const incoming = mine.filter(d => d.to === id), outgoing = mine.filter(d => d.from === id);
  if (!c) return <div className="panel-body"><p>Not found.</p></div>;
  return (
    <div className="panel-body" key={id}>
      <p className="kicker"><LayerTag index={index} layer={c.layer} theme={theme} />{c.ticker && <span className="ticker">{c.ticker}</span>}{!c.ticker && <span className="ticker">Private</span>}</p>
      <h1 className="display">{c.name}</h1>
      <p className="lede">{c.does}</p>

      {outgoing.length > 0 && <section>
        <h2>Pays, invests in or buys from <span className="count">{outgoing.length}</span></h2>
        <ul className="plain">{outgoing.map(d => <DealRow key={d.id} d={d} index={index} theme={theme} nav={nav} viewpoint={id} />)}</ul>
      </section>}
      {incoming.length > 0 && <section>
        <h2>Paid by, funded by or sells to <span className="count">{incoming.length}</span></h2>
        <ul className="plain">{incoming.map(d => <DealRow key={d.id} d={d} index={index} theme={theme} nav={nav} viewpoint={id} />)}</ul>
      </section>}
      {!mine.length && <p className="empty">No deals match the current filters.</p>}
      {hidden > 0 && <p className="note">{hidden} more hidden by the current filters.</p>}

      {c.fin && <Financials fin={c.fin} asOf={index.data.fundamentals_as_of} />}
    </div>
  );
}

// ---------------------------------------------------------------- deal
export function DealPanel({ id, index, theme, nav }: Common & { id: string }) {
  const d = index.dealById[id];
  if (!d) return <div className="panel-body"><p>Not found.</p></div>;
  const from = index.byId[d.from], to = index.byId[d.to];
  const t = TYPES[d.type], st = d.status ? STATUSES[d.status] : null, ev = d.evidence ? EVIDENCE[d.evidence] : null;
  return (
    <div className="panel-body" key={id}>
      <p className="kicker"><TypeTag type={d.type} theme={theme} /><span className="ticker">{dateLabel(d.date)}</span></p>
      <h1 className="display deal-title">
        <CompanyLink c={from} nav={nav} />
        <span className="verb">{t?.verb || "deals with"}</span>
        <CompanyLink c={to} nav={nav} />
      </h1>
      <p className="lede">{d.summary}</p>
      <dl className="facts">
        {st && <div><dt>Status</dt><dd><span className={"tag status " + d.status}>{st.label}</span><span className="hint">{st.hint}</span></dd></div>}
        {ev && <div><dt>Best evidence</dt><dd>{ev.label}<span className="hint">{ev.hint}</span></dd></div>}
      </dl>
      <section>
        <h2>Sources <span className="count">{d.sources.length}</span></h2>
        <ul className="plain sources">
          {d.sources.map((s, i) => (
            <li key={i}><a href={s.url} target="_blank" rel="noopener noreferrer">
              <span>{s.source || new URL(s.url).hostname.replace(/^www\./, "")}</span>
              <span className="date">{dateLabel(s.published)} ↗</span></a></li>
          ))}
        </ul>
        <p className="note">Amounts are left out on purpose: they come from news reports, not official filings. The sources have the details.</p>
      </section>
    </div>
  );
}

// ---------------------------------------------------------------- about
export function About({ index }: { index: Index }) {
  const { data } = index;
  return (
    <div className="panel-body prose">
      <p className="kicker">Method</p>
      <h1 className="display">How this map is made</h1>
      <p>A script searches Google News and the PR Newswire and GlobeNewswire press wires month by month, from November 2024 to {dateLabel(data.covered_until)}. It reads each article it is allowed to read. Claude, an AI model, picks out the deals. Every deal must quote its source text, and both parties must be known companies.</p>
      <h2>What is shown</h2>
      <p>Who dealt with whom, the kind of deal, its status and date, and links to the reports. Each deal is marked with its best evidence: a company press release, a news article, a news summary, or only a headline.</p>
      <h2>What is not</h2>
      <p>Deal amounts. Reported figures are often estimates, "up to" ceilings or multi-year totals, and they don't come from official filings, so we leave them out. Deals we could not match to any report are left out too.</p>
      <h2>Financials and market data</h2>
      <p>Revenue, earnings and capital spending come from the companies' SEC filings (EDGAR, as of {dateLabel(data.fundamentals_as_of)}). Prices and valuation ratios are live from TradingView.</p>
      <h2>Limits</h2>
      <p>News coverage is uneven, paywalled stories may be read only by headline, and an AI can misread an article. Treat this as a map to the sources, not a source in itself. Nothing here is investment advice.</p>
    </div>
  );
}
