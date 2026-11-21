import { useEffect, useMemo, useRef, useState } from "react";
import type { Index } from "../data";
import { LAYER_COLORS, type Theme } from "../meta";

export default function Search({ index, theme, onPick }: { index: Index; theme: Theme; onPick: (id: string) => void }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [sel, setSel] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  const results = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return [];
    const score = (name: string, ticker: string) =>
      ticker === s ? 0 : name.startsWith(s) ? 1 : name.split(/[\s(]+/).some(w => w.startsWith(s)) ? 2 : name.includes(s) || ticker.startsWith(s) ? 3 : 9;
    return index.data.companies
      .map(c => ({ c, r: score(c.name.toLowerCase(), (c.ticker || "").toLowerCase()) }))
      .filter(x => x.r < 9).sort((a, b) => a.r - b.r || a.c.name.localeCompare(b.c.name)).slice(0, 8).map(x => x.c);
  }, [q, index]);

  useEffect(() => {
    const f = (e: KeyboardEvent) => {
      const typing = ["INPUT", "TEXTAREA", "SELECT"].includes((e.target as HTMLElement).tagName);
      if ((e.key === "/" && !typing) || (e.key === "k" && (e.metaKey || e.ctrlKey))) {
        e.preventDefault(); input.current?.focus(); input.current?.select();
      }
    };
    window.addEventListener("keydown", f);
    return () => window.removeEventListener("keydown", f);
  }, []);

  const pick = (id: string) => { onPick(id); setQ(""); setOpen(false); input.current?.blur(); };

  return (
    <div className="search" role="combobox" aria-expanded={open && results.length > 0} aria-haspopup="listbox">
      <input ref={input} value={q} placeholder="Find a company" aria-label="Find a company"
        onChange={e => { setQ(e.target.value); setOpen(true); setSel(0); }}
        onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 120)}
        onKeyDown={e => {
          if (e.key === "ArrowDown") { e.preventDefault(); setSel(s => Math.min(s + 1, results.length - 1)); }
          if (e.key === "ArrowUp") { e.preventDefault(); setSel(s => Math.max(s - 1, 0)); }
          if (e.key === "Enter" && results[sel]) pick(results[sel].id);
          if (e.key === "Escape") { setQ(""); input.current?.blur(); }
        }} />
      <kbd aria-hidden>/</kbd>
      {open && results.length > 0 && (
        <ul className="results" role="listbox">
          {results.map((c, i) => (
            <li key={c.id} role="option" aria-selected={i === sel} className={i === sel ? "on" : ""}
              onMouseDown={e => { e.preventDefault(); pick(c.id); }} onMouseEnter={() => setSel(i)}>
              <i className="dot" style={{ background: LAYER_COLORS[theme][(index.layerIndex[c.layer] ?? 0) % 9] }} />
              <span>{c.name}</span>{c.ticker && <span className="ticker">{c.ticker}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
