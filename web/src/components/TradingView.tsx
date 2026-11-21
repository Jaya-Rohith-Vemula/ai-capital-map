import { useEffect, useRef } from "react";
import type { Theme } from "../meta";
import type { Company } from "../types";

const EXCHANGE: Record<string, string> = { Nasdaq: "NASDAQ", NYSE: "NYSE", CBOE: "CBOE", OTC: "OTC", "NYSE American": "AMEX", "NYSE Arca": "AMEX" };

// The TradingView symbol: `market` from companies.json, else SEC's exchange + ticker.
export function tvSymbol(c: Company): string | null {
  if (!c.ticker || c.market === false) return null;
  if (c.market) return c.market;
  if (c.fin && EXCHANGE[c.fin.exchange]) return `${EXCHANGE[c.fin.exchange]}:${c.ticker}`;
  return c.ticker.includes(".") ? null : c.ticker;
}

function Widget({ kind, config, symbol }: { kind: string; config: object; symbol: string }) {
  const box = useRef<HTMLDivElement>(null);
  const cfg = JSON.stringify(config);
  useEffect(() => {
    const el = box.current; if (!el) return;
    el.innerHTML = '<div class="tradingview-widget-container__widget"></div>';
    const s = document.createElement("script");
    s.src = `https://s3.tradingview.com/external-embedding/embed-widget-${kind}.js`;
    s.async = true;
    s.text = cfg;
    el.appendChild(s);
    return () => { el.innerHTML = ""; };
  }, [kind, cfg]);
  return (
    <div className="tv">
      <div className="tradingview-widget-container" ref={box} />
      <div className="tradingview-widget-copyright">
        <a href={`https://www.tradingview.com/symbols/${symbol.replace(":", "-")}/`} rel="noopener nofollow" target="_blank">{symbol} on TradingView</a>
      </div>
    </div>
  );
}

export default function TradingView({ symbol, theme }: { symbol: string; theme: Theme }) {
  const common = { symbol, locale: "en", colorTheme: theme, isTransparent: true, width: "100%" };
  return (
    <>
      <Widget kind="symbol-info" symbol={symbol} config={common} />
      <Widget kind="financials" symbol={symbol} config={{ ...common, height: 540, displayMode: "regular" }} />
      <p className="note">Price, P/E, EPS and market cap, live from TradingView.</p>
    </>
  );
}
