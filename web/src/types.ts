export type Layer = { id: string; name: string };

export type FinRow = { end: string; revenue?: number; net_income?: number; eps?: number; capex?: number; ocf?: number };

export type Fin = {
  currency: string | null;
  annual: FinRow[];
  quarterly: FinRow[];
  last_filed: string | null;
  cik: number;
  exchange: string;
};

export type Company = {
  id: string;
  name: string;
  ticker: string | null;
  layer: string;
  does: string;
  market?: string | false;
  fin?: Fin;
};

export type Source = { source: string | null; published: string | null; url: string };

export type Deal = {
  id: string;
  from: string;
  to: string;
  type: string;
  status: string | null;
  date: string | null;
  evidence: string | null;
  summary: string;
  first_seen: string | null;
  sources: Source[];
};

export type Data = {
  built_at: string;
  covered_until: string | null;
  start: string | null;
  fundamentals_as_of: string | null;
  layers: Layer[];
  companies: Company[];
  deals: Deal[];
};

export type View =
  | { kind: "overview" }
  | { kind: "company"; id: string }
  | { kind: "deal"; id: string }
  | { kind: "about" };
