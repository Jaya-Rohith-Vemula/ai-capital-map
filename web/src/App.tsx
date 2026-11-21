import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { buildIndex, dealMonth, monthLabel, type Index } from "./data";
import { LAYER_COLORS, STATUSES, TYPES, type Theme } from "./meta";
import type { Data, View } from "./types";
import Graph, { type GraphApi } from "./components/Graph";
import { About, CompanyPanel, DealPanel, Overview } from "./components/Panels";
import Search from "./components/Search";

// ---- routing: #/c/NVDA, #/d/d006, #/about ----
function parseHash(index: Index | null): View {
  const h = decodeURIComponent(location.hash.replace(/^#\/?/, ""));
  const [k, id] = h.split("/");
  if (k === "about") return { kind: "about" };
  if (k === "d" && id) return { kind: "deal", id };
  if (k === "c" && id) return { kind: "company", id };
  // #NVDA or #/NVDA: a ticker or company id
  if (index && k) {
    const q = k.toLowerCase();
    const c = index.data.companies.find(c => c.id.toLowerCase() === q || (c.ticker || "").toLowerCase() === q);
    if (c) return { kind: "company", id: c.id };
  }
  return { kind: "overview" };
}
const hashOf = (v: View) => v.kind === "company" ? `#/c/${v.id}` : v.kind === "deal" ? `#/d/${v.id}` : v.kind === "about" ? "#/about" : "";

function useTheme(): [Theme, (t: Theme | "system") => void, Theme | "system"] {
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  const [pref, setPref] = useState<Theme | "system">(() => {
    try { return (localStorage.getItem("theme") as Theme) || "system"; } catch { return "system"; }
  });
  const [sys, setSys] = useState<Theme>(media.matches ? "dark" : "light");
  useEffect(() => {
    const f = (e: MediaQueryListEvent) => setSys(e.matches ? "dark" : "light");
    media.addEventListener("change", f);
    return () => media.removeEventListener("change", f);
  }, []);
  const theme = pref === "system" ? sys : pref;
  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);
  const set = (t: Theme | "system") => {
    setPref(t);
    try { t === "system" ? localStorage.removeItem("theme") : localStorage.setItem("theme", t); } catch { /* private mode */ }
  };
  return [theme, set, pref];
}

export default function App() {
  const [index, setIndex] = useState<Index | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    fetch("/data.json").then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((d: Data) => setIndex(buildIndex(d))).catch(e => setError(String(e)));
  }, []);
  if (error) return <div className="splash"><p>Couldn't load the map data ({error}).</p></div>;
  if (!index) return <div className="splash"><p className="pulse">Loading the map…</p></div>;
  return <MapApp index={index} />;
}

function MapApp({ index }: { index: Index }) {
  const { data } = index;
  const [theme, setTheme, themePref] = useTheme();
  const [view, setView] = useState<View>(() => parseHash(index));
  const [types, setTypes] = useState<Set<string>>(() => new Set(Object.keys(TYPES)));
  const [layers, setLayers] = useState<Set<string>>(() => new Set(data.layers.map(l => l.id)));
  const [statuses, setStatuses] = useState<Set<string>>(() => new Set(["announced", "completed", "loi", "reported"]));
  const [primary, setPrimary] = useState(false);
  const [month, setMonth] = useState(index.months.length - 1);
  const [playing, setPlaying] = useState(false);
  const [layout, setLayout] = useState<"columns" | "web">("columns");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const graph = useRef<GraphApi | null>(null);
  const panel = useRef<HTMLElement>(null);

  // ---- navigation ----
  const go = useCallback((v: View) => {
    setView(v);
    const h = hashOf(v);
    if (location.hash !== h) history.pushState(null, "", h || location.pathname);
    panel.current?.scrollTo({ top: 0 });
  }, []);
  useEffect(() => {
    // Back fires both popstate and hashchange; only the first may change the view.
    const f = () => { const v = parseHash(index); setView(cur => hashOf(cur) === hashOf(v) ? cur : v); };
    window.addEventListener("popstate", f);
    window.addEventListener("hashchange", f);
    return () => { window.removeEventListener("popstate", f); window.removeEventListener("hashchange", f); };
  }, [index]);
  const nav = useMemo(() => ({
    company: (id: string) => go({ kind: "company", id }),
    deal: (id: string) => go({ kind: "deal", id }),
    about: () => go({ kind: "about" }),
  }), [go]);

  // ---- filtering ----
  const start = (data.start || "2024-11").slice(0, 7);
  const until = index.months[month];
  const visible = useMemo(() => {
    const s = new Set<string>();
    for (const d of data.deals) {
      const a = index.byId[d.from], b = index.byId[d.to];
      if (!a || !b) continue;
      if (!types.has(d.type) || !statuses.has(d.status || "announced")) continue;
      if (!layers.has(a.layer) || !layers.has(b.layer)) continue;
      if (primary && d.evidence !== "press release") continue;
      if (dealMonth(d, start) > until) continue;
      s.add(d.id);
    }
    return s;
  }, [data, index, types, statuses, layers, primary, until, start]);

  // ---- timeline playback ----
  useEffect(() => {
    if (!playing) return;
    const t = setInterval(() => setMonth(m => {
      if (m >= index.months.length - 1) { setPlaying(false); return m; }
      return m + 1;
    }), 650);
    return () => clearInterval(t);
  }, [playing, index.months.length]);
  const play = () => {
    if (playing) return setPlaying(false);
    if (month >= index.months.length - 1) setMonth(0);
    setPlaying(true);
  };

  // ---- keyboard ----
  useEffect(() => {
    const f = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
      if (e.key === "Escape") go({ kind: "overview" });
      if (e.key === "f" || e.key === "F") graph.current?.fit();
      if (e.key === "+" || e.key === "=") graph.current?.zoom(1.3);
      if (e.key === "-") graph.current?.zoom(1 / 1.3);
    };
    window.addEventListener("keydown", f);
    return () => window.removeEventListener("keydown", f);
  }, [go]);

  const toggle = (set: Set<string>, setter: (s: Set<string>) => void, k: string) => {
    const n = new Set(set); n.has(k) ? n.delete(k) : n.add(k); setter(n);
  };
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    data.deals.forEach(d => (c[d.type] = (c[d.type] || 0) + 1));
    return c;
  }, [data]);
  const filtered = types.size < Object.keys(TYPES).length || layers.size < data.layers.length || primary
    || statuses.size !== 4 || !statuses.has("announced") || month < index.months.length - 1;
  const reset = () => {
    setTypes(new Set(Object.keys(TYPES))); setLayers(new Set(data.layers.map(l => l.id)));
    setStatuses(new Set(["announced", "completed", "loi", "reported"])); setPrimary(false);
    setMonth(index.months.length - 1); setPlaying(false);
  };

  return (
    <div className={"app" + (filtersOpen ? " filters-open" : "")}>
      <header className="top">
        <button className="brand" onClick={() => go({ kind: "overview" })} aria-label="AI Capital Map, overview">
          <span className="mark" aria-hidden>◐</span><span>AI Capital Map</span>
        </button>
        <Search index={index} theme={theme} onPick={id => nav.company(id)} />
        <nav className="top-actions">
          <button className={"ghost filters-btn" + (filtered ? " on" : "")} onClick={() => setFiltersOpen(o => !o)} aria-expanded={filtersOpen}>
            Filters{filtered ? " •" : ""}
          </button>
          <button className="ghost" onClick={nav.about}>About</button>
          <button className="ghost icon" title={`Theme: ${themePref}`} aria-label="Change theme"
            onClick={() => setTheme(themePref === "system" ? (theme === "dark" ? "light" : "dark") : themePref === "dark" ? "light" : "system")}>
            {themePref === "system" ? "◑" : theme === "dark" ? "☾" : "☀"}
          </button>
        </nav>
      </header>

      <aside className="filters" aria-label="Filters">
        <div className="filters-inner">
          <div className="fgroup">
            <h3>Kind of deal</h3>
            {Object.entries(TYPES).filter(([k]) => counts[k]).map(([k, t]) => (
              <label key={k} className="check">
                <input type="checkbox" checked={types.has(k)} onChange={() => toggle(types, setTypes, k)} />
                <i className="bar" style={{ background: t[theme] }} />{t.label}<span className="num">{counts[k]}</span>
              </label>
            ))}
          </div>
          <div className="fgroup">
            <h3>Part of the stack</h3>
            {data.layers.map((l, i) => (
              <label key={l.id} className="check">
                <input type="checkbox" checked={layers.has(l.id)} onChange={() => toggle(layers, setLayers, l.id)} />
                <i className="dot" style={{ background: LAYER_COLORS[theme][i % 9] }} />{l.name}
              </label>
            ))}
          </div>
          <div className="fgroup">
            <h3>Status</h3>
            {Object.entries(STATUSES).map(([k, s]) => (
              <label key={k} className="check" title={s.hint}>
                <input type="checkbox" checked={statuses.has(k)} onChange={() => toggle(statuses, setStatuses, k)} />
                <i className={"line " + k} />{s.label}
              </label>
            ))}
          </div>
          <div className="fgroup">
            <h3>Evidence</h3>
            <label className="check switch">
              <input type="checkbox" checked={primary} onChange={e => setPrimary(e.target.checked)} />
              <span className="knob" aria-hidden />Only deals in a company press release
            </label>
          </div>
          <div className="fgroup">
            <h3>Arrangement</h3>
            <div className="seg" role="radiogroup">
              <button role="radio" aria-checked={layout === "columns"} className={layout === "columns" ? "on" : ""} onClick={() => setLayout("columns")}>By layer</button>
              <button role="radio" aria-checked={layout === "web"} className={layout === "web" ? "on" : ""} onClick={() => setLayout("web")}>Web</button>
            </div>
          </div>
          {filtered && <button className="ghost reset" onClick={reset}>Reset filters</button>}
        </div>
      </aside>

      <main className="stage">
        <Graph index={index} visible={visible} view={view} theme={theme} layout={layout} apiRef={graph}
          onCompany={nav.company} onDeal={nav.deal} onBackground={() => go({ kind: "overview" })} />
        <div className="zoom" role="group" aria-label="Zoom">
          <button onClick={() => graph.current?.zoom(1.3)} aria-label="Zoom in">+</button>
          <button onClick={() => graph.current?.zoom(1 / 1.3)} aria-label="Zoom out">−</button>
          <button onClick={() => graph.current?.fit()} aria-label="Fit everything" title="Fit (F)">⤢</button>
        </div>
        <div className="timeline">
          <button className="play" onClick={play} aria-label={playing ? "Pause" : "Play the timeline"}>{playing ? "❚❚" : "▶"}</button>
          <input type="range" min={0} max={index.months.length - 1} value={month} aria-label="Show deals up to"
            onChange={e => { setPlaying(false); setMonth(+e.target.value); }}
            style={{ ["--p" as string]: `${(month / Math.max(1, index.months.length - 1)) * 100}%` }} />
          <span className="when"><small>through</small> {monthLabel(until)}</span>
          <span className="shown">{visible.size} deals</span>
        </div>
      </main>

      <aside className="inspector" ref={panel} aria-live="polite">
        {view.kind !== "overview" && (
          <button className="back" onClick={() => history.length > 1 ? history.back() : go({ kind: "overview" })}>← Back</button>
        )}
        {view.kind === "overview" && <Overview index={index} visible={visible} theme={theme} nav={nav} />}
        {view.kind === "company" && <CompanyPanel id={view.id} index={index} visible={visible} theme={theme} nav={nav} />}
        {view.kind === "deal" && <DealPanel id={view.id} index={index} visible={visible} theme={theme} nav={nav} />}
        {view.kind === "about" && <About index={index} />}
      </aside>
    </div>
  );
}
