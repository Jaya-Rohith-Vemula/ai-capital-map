import { useCallback, useState } from "react";

// A value remembered across visits (per browser); storage may be unavailable.
export function useStored(key: string, initial: number): [number, (v: number) => void] {
  const [v, setV] = useState(() => {
    try { const s = localStorage.getItem(key); if (s != null && isFinite(+s)) return +s; } catch { /* ignore */ }
    return initial;
  });
  const set = useCallback((n: number) => {
    setV(n);
    try { localStorage.setItem(key, String(n)); } catch { /* ignore */ }
  }, [key]);
  return [v, set];
}

type Props = {
  orientation: "vertical" | "horizontal"; // vertical = drag left/right
  className: string;
  label: string;
  value: number; min: number; max: number; step: number;
  // Turn a pointer position into a new value.
  fromPointer: (e: PointerEvent) => number;
  onChange: (v: number) => void;
  onReset: () => void;
};

// A draggable divider. While dragging, iframes (TradingView) can't swallow the pointer.
export default function Splitter({ orientation, className, label, value, min, max, step, fromPointer, onChange, onReset }: Props) {
  const clamp = (n: number) => Math.min(max, Math.max(min, n));
  const down = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    e.preventDefault();
    document.body.classList.add("resizing", orientation === "vertical" ? "resizing-x" : "resizing-y");
    const move = (ev: PointerEvent) => { onChange(clamp(fromPointer(ev))); window.dispatchEvent(new Event("resize")); };
    const up = () => {
      document.body.classList.remove("resizing", "resizing-x", "resizing-y");
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.dispatchEvent(new Event("resize"));
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };
  const key = (e: React.KeyboardEvent) => {
    const dec = orientation === "vertical" ? "ArrowRight" : "ArrowUp";
    const inc = orientation === "vertical" ? "ArrowLeft" : "ArrowDown";
    if (e.key === dec || e.key === inc) {
      e.preventDefault();
      onChange(clamp(value + (e.key === inc ? step : -step)));
      window.dispatchEvent(new Event("resize"));
    }
  };
  return (
    <div className={"splitter " + className} role="separator" tabIndex={0}
      aria-orientation={orientation} aria-label={label}
      aria-valuenow={Math.round(value)} aria-valuemin={min} aria-valuemax={max}
      title="Drag to resize · double-click to reset"
      onPointerDown={down} onKeyDown={key}
      onDoubleClick={() => { onReset(); window.dispatchEvent(new Event("resize")); }}>
      <span className="grip" aria-hidden="true">
        {orientation === "vertical"
          ? <svg viewBox="0 0 12 20" width="12" height="20"><path d="M4.5 6.5 1.5 10l3 3.5M7.5 6.5l3 3.5-3 3.5" /></svg>
          : <svg viewBox="0 0 20 12" width="20" height="12"><path d="M6.5 4.5 10 1.5l3.5 3M6.5 7.5l3.5 3 3.5-3" /></svg>}
      </span>
    </div>
  );
}
