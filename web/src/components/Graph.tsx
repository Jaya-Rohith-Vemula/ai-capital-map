import { useEffect, useRef } from "react";
import cytoscape from "cytoscape";
import type { Core, ElementDefinition, NodeSingular } from "cytoscape";
import type { Index } from "../data";
import { LAYER_COLORS, TYPES, type Theme } from "../meta";
import type { View } from "../types";

type Props = {
  index: Index;
  visible: Set<string>;          // deal ids passing the filters
  view: View;
  theme: Theme;
  layout: "columns" | "web";
  onCompany: (id: string) => void;
  onDeal: (id: string) => void;
  onBackground: () => void;
  apiRef?: React.MutableRefObject<GraphApi | null>;
};

export type GraphApi = { zoom: (f: number) => void; fit: () => void };

const INK = { light: { ink: "#1F1D1A", soft: "#8C877C", bg: "#F6F3EC", label: "#857E70" },
              dark: { ink: "#ECE8DF", soft: "#7E7A72", bg: "#15140F", label: "#7A766C" } };

function columnPositions(index: Index, degree: Record<string, number>) {
  const pos: Record<string, { x: number; y: number }> = {}, headers: Record<string, { x: number; y: number }> = {};
  const colW = 270, rowH = 118, maxRows = 13, sub = 118;
  let x = 0, li = 0;
  for (const l of index.data.layers) {
    const members = index.data.companies.filter(c => c.layer === l.id).sort((a, b) => degree[b.id] - degree[a.id]);
    if (!members.length) continue;
    // Busiest in the middle of the column, alternating above and below.
    const ordered: typeof members = [];
    members.forEach((c, i) => (i % 2 ? ordered.push(c) : ordered.unshift(c)));
    const cols = Math.max(1, Math.ceil(ordered.length / maxRows));
    const per = Math.ceil(ordered.length / cols);
    let top = 0;
    for (let s = 0; s < cols; s++) {
      const chunk = ordered.slice(s * per, (s + 1) * per);
      chunk.forEach((c, i) => {
        const y = (i - (chunk.length - 1) / 2) * rowH + (s % 2) * rowH / 2;
        pos[c.id] = { x: x + s * sub, y };
        top = Math.min(top, y);
      });
    }
    // Alternate heights so neighbouring titles never collide.
    headers[l.id] = { x: x + ((cols - 1) * sub) / 2, y: top - 110 - (li++ % 2) * 72 };
    x += colW + (cols - 1) * sub;
  }
  return { pos, headers };
}

export default function Graph({ index, visible, view, theme, layout, onCompany, onDeal, onBackground, apiRef }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const handlers = useRef({ onCompany, onDeal, onBackground });
  handlers.current = { onCompany, onDeal, onBackground };

  // ---- build once ----
  useEffect(() => {
    const { data, layerIndex } = index;
    const degree: Record<string, number> = {};
    data.companies.forEach(c => (degree[c.id] = 0));
    const pairs = new Set<string>();
    data.deals.forEach(d => {
      const k = [d.from, d.to].sort().join("|");
      if (pairs.has(k)) return;
      pairs.add(k);
      degree[d.from]++; degree[d.to]++;
    });
    const { pos, headers } = columnPositions(index, degree);
    const els: ElementDefinition[] = [];
    data.layers.forEach(l => headers[l.id] && els.push({
      group: "nodes", data: { id: "L:" + l.id, label: l.name }, position: headers[l.id], classes: "layer",
      selectable: false, grabbable: false,
    }));
    data.companies.forEach(c => {
      const deg = degree[c.id] || 0;
      els.push({
        group: "nodes", position: pos[c.id],
        data: { id: c.id, label: c.name, li: layerIndex[c.layer] ?? 0, size: Math.min(74, 16 + Math.sqrt(deg) * 9), fs: Math.min(26, 13 + Math.sqrt(deg) * 1.7) },
      });
    });
    data.deals.forEach(d => {
      if (!index.byId[d.from] || !index.byId[d.to]) return;
      els.push({ group: "edges", data: { id: d.id, source: d.from, target: d.to, type: d.type },
        classes: d.status === "loi" || d.status === "reported" ? "soft" : d.status === "terminated" ? "ended" : "" });
    });

    const cy = cytoscape({
      container: box.current, elements: els, layout: { name: "preset" },
      minZoom: 0.12, maxZoom: 3, wheelSensitivity: 0.3, boxSelectionEnabled: false, autoungrabify: false,
    });
    // Copies: cytoscape moves the objects it was given in place, so the originals drift with every layout.
    cy.scratch("_pos", structuredClone(pos));
    cy.scratch("_headers", structuredClone(headers));
    cyRef.current = cy;

    cy.on("tap", "node", e => { const n = e.target as NodeSingular; if (!n.hasClass("layer")) handlers.current.onCompany(n.id()); });
    cy.on("tap", "edge", e => handlers.current.onDeal(e.target.id()));
    cy.on("tap", e => { if (e.target === cy) handlers.current.onBackground(); });
    cy.on("mouseover", "node", e => {
      const n = e.target as NodeSingular;
      if (n.hasClass("layer")) return;
      box.current!.style.cursor = "pointer";
      if (cy.scratch("_selected")) return;
      const hood = n.closedNeighborhood().not(".hidden");
      cy.elements().not(hood).not(".layer").addClass("hdim");
      hood.edges().addClass("lit");
    });
    cy.on("mouseout", "node", () => {
      box.current!.style.cursor = "";
      if (!cy.scratch("_selected")) cy.elements().removeClass("hdim lit");
    });
    cy.on("mouseover", "edge", e => { box.current!.style.cursor = "pointer"; e.target.addClass("hl"); });
    cy.on("mouseout", "edge", e => { box.current!.style.cursor = ""; e.target.removeClass("hl"); });

    cy.fit(undefined, 40);
    if (apiRef) apiRef.current = {
      zoom: f => cy.animate({ zoom: { level: cy.zoom() * f, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } } }, { duration: 200 }),
      fit: () => cy.animate({ fit: { eles: cy.elements().not(".hidden"), padding: 40 } }, { duration: 350, easing: "ease-out-quart" as never }),
    };
    return () => cy.destroy();
  }, [index]);

  // ---- theme ----
  useEffect(() => {
    const cy = cyRef.current; if (!cy) return;
    const k = INK[theme], lc = LAYER_COLORS[theme];
    cy.edges().forEach(e => { e.data("c", TYPES[e.data("type")]?.[theme] || k.soft); });
    cy.style([
      { selector: "node", style: {
        "background-color": (n: NodeSingular) => lc[n.data("li") % lc.length], width: "data(size)", height: "data(size)",
        label: "data(label)", "font-family": "Geist, system-ui, sans-serif", "font-size": "data(fs)", "font-weight": 500,
        color: k.ink, "text-valign": "bottom", "text-margin-y": 5, "text-wrap": "wrap", "text-max-width": "150px",
        "text-outline-color": k.bg, "text-outline-width": 2.5, "min-zoomed-font-size": 8,
        "border-width": 2, "border-color": k.bg, "transition-property": "opacity background-color", "transition-duration": 180,
      } as never },
      { selector: "node.layer", style: {
        "background-opacity": 0, "border-width": 0, width: 1, height: 1, label: "data(label)",
        "font-family": "'Instrument Serif', Georgia, serif", "font-size": 40, "text-wrap": "none", "font-weight": 400, color: k.label,
        "text-valign": "center", "text-outline-width": 0, "min-zoomed-font-size": 6, events: "no",
      } as never },
      { selector: "edge", style: {
        "curve-style": "bezier", "control-point-step-size": 22, width: 1.2, "line-color": k.ink, "target-arrow-color": k.ink,
        "target-arrow-shape": "triangle", "arrow-scale": 0.7, opacity: 0.16,
        "transition-property": "opacity line-color width", "transition-duration": 180,
      } as never },
      { selector: "edge.soft", style: { "line-style": "dashed", "line-dash-pattern": [5, 4] } as never },
      { selector: "edge.ended", style: { "line-style": "dotted", "target-arrow-shape": "tee" } as never },
      { selector: "edge.lit, edge.hl", style: { "line-color": "data(c)", "target-arrow-color": "data(c)", width: 2.4, opacity: 0.95, "z-index": 10 } as never },
      { selector: "node.sel", style: { "border-color": k.ink, "border-width": 3 } as never },
      { selector: ".dim, .hdim", style: { opacity: 0.1 } as never },
      { selector: "node.dim, node.hdim", style: { "text-opacity": 0 } as never },
      { selector: ".hidden", style: { display: "none" } as never },
    ]);
  }, [theme, index]);

  // ---- filters ----
  useEffect(() => {
    const cy = cyRef.current; if (!cy) return;
    cy.batch(() => {
      cy.edges().forEach(e => { e.toggleClass("hidden", !visible.has(e.id())); });
      cy.nodes().not(".layer").forEach(n => { n.toggleClass("hidden", n.connectedEdges().not(".hidden").length === 0); });
      // A layer's title goes when none of its companies are left.
      const shown = new Set(cy.nodes().not(".layer").not(".hidden").map(n => n.data("li")));
      cy.nodes(".layer").forEach(n => { n.toggleClass("hidden", !shown.has(index.layerIndex[n.id().slice(2)])); });
    });
  }, [visible]);

  // ---- selection ----
  const vid = view.kind === "company" || view.kind === "deal" ? view.id : "";
  const home = useRef<{ zoom: number; pan: { x: number; y: number } } | null>(null);
  useEffect(() => {
    const cy = cyRef.current; if (!cy) return;
    let focus = null;
    if (view.kind === "company") {
      const n = cy.getElementById(vid);
      if (n.length) { n.removeClass("hidden"); focus = n.closedNeighborhood().not(".hidden").union(n); }
    } else if (view.kind === "deal") {
      const e = cy.getElementById(vid);
      if (e.length) { e.removeClass("hidden"); e.connectedNodes().removeClass("hidden"); focus = e.union(e.connectedNodes()); }
    }
    // Remember where the reader was before the first selection, to return there afterwards.
    if (focus && !cy.scratch("_selected")) home.current = { zoom: cy.zoom(), pan: { ...cy.pan() } };
    cy.batch(() => {
      cy.elements().removeClass("dim hdim lit sel");
      if (!focus) return;
      cy.elements().not(focus).not(".layer").addClass("dim");
      focus.edges().addClass("lit");
      if (view.kind === "company") cy.getElementById(vid).addClass("sel");
    });
    cy.scratch("_selected", !!focus);
    cy.stop(true, false);
    if (!focus) {
      if (home.current) cy.animate(home.current, { duration: 450, easing: "ease-out-quart" as never });
      home.current = null;
      return;
    }
    // Fit the selection, but never zoom in past `cap`: two nodes alone would fill the screen.
    const bb = focus.boundingBox(), pad = 110, cap = view.kind === "deal" ? 1.1 : 1.3;
    const zoom = Math.min(cap, (cy.width() - 2 * pad) / Math.max(bb.w, 1), (cy.height() - 2 * pad) / Math.max(bb.h, 1));
    const center = { x: (bb.x1 + bb.x2) / 2, y: (bb.y1 + bb.y2) / 2 };
    cy.animate({ zoom, pan: { x: cy.width() / 2 - center.x * zoom, y: cy.height() / 2 - center.y * zoom } },
      { duration: 450, easing: "ease-out-quart" as never });
  }, [view.kind, vid]);

  // ---- layout (the initial columns are already in place from the build) ----
  const firstLayout = useRef(true);
  const running = useRef<cytoscape.Layouts | null>(null);
  useEffect(() => {
    const cy = cyRef.current; if (!cy) return;
    if (firstLayout.current) { firstLayout.current = false; return; }
    // A force layout keeps moving nodes until it finishes; stop it before switching.
    running.current?.stop();
    cy.stop(true, true);
    cy.nodes().stop(true, false);
    const real = cy.nodes().not(".layer");
    if (layout === "columns") {
      const pos = cy.scratch("_pos") as Record<string, { x: number; y: number }>;
      const headers = cy.scratch("_headers") as Record<string, { x: number; y: number }>;
      const layers = cy.nodes(".layer");
      layers.removeStyle("display");
      layers.forEach(n => { n.position(headers[n.id().slice(2)]); });
      real.forEach(n => { n.animate({ position: pos[n.id()] }, { duration: 500, easing: "ease-out-quart" as never }); });
      running.current = null;
      // Fit once the nodes have arrived; fitting now would frame the old positions.
      const t = setTimeout(() => cy.animate({ fit: { eles: cy.elements().not(".hidden"), padding: 40 } }, { duration: 350, easing: "ease-out-quart" as never }), 520);
      return () => clearTimeout(t);
    } else {
      cy.nodes(".layer").style("display", "none");
      running.current = real.not(".hidden").union(cy.edges().not(".hidden")).layout({
        name: "cose", animate: true, animationDuration: 700, nodeRepulsion: () => 120000, idealEdgeLength: () => 120,
        gravity: 0.3, numIter: 1500, padding: 40, randomize: false,
      } as never);
      running.current.run();
    }
  }, [layout]);

  return <div ref={box} className="graph" aria-label="Map of deals between companies" role="img" />;
}
