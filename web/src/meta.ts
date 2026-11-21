// Labels and colours for the data. Hex, because the graph canvas needs them.

export type Theme = "light" | "dark";

export const LAYER_COLORS: Record<Theme, string[]> = {
  light: ["#9A6B2F", "#D0461A", "#2457C5", "#0E8A7E", "#7A4EC2", "#4D8A1F", "#C2367A", "#5B6B7F", "#B58E00", "#1F7FA8"],
  dark: ["#D6A866", "#FF8052", "#76A0FF", "#44CBB8", "#B394F2", "#93CF5A", "#F477B0", "#A3B1C2", "#EDCB4A", "#5EC4EC"],
};

export const TYPES: Record<string, { label: string; verb: string; light: string; dark: string }> = {
  equity: { label: "Equity investment", verb: "invests in", light: "#2457C5", dark: "#76A0FF" },
  compute: { label: "Compute / cloud", verb: "buys compute from", light: "#0E8A7E", dark: "#44CBB8" },
  chips: { label: "Chips & hardware", verb: "buys hardware from", light: "#7A4EC2", dark: "#B394F2" },
  lease: { label: "Data-center lease", verb: "leases capacity from", light: "#B26A00", dark: "#F2A945" },
  power: { label: "Power", verb: "buys power from", light: "#9C8300", dark: "#E8CF4A" },
  financing: { label: "Financing", verb: "finances", light: "#C2367A", dark: "#F477B0" },
  acquisition: { label: "Acquisition", verb: "acquires", light: "#3B3F46", dark: "#E4E1D8" },
  partnership: { label: "Partnership", verb: "partners with", light: "#6B7380", dark: "#9AA3AE" },
};

export const STATUSES: Record<string, { label: string; hint: string }> = {
  announced: { label: "Announced", hint: "Signed and confirmed by the companies." },
  completed: { label: "Completed", hint: "Closed or fully delivered." },
  loi: { label: "Letter of intent", hint: "Memorandum, framework or milestone-based commitment; not yet definitive." },
  reported: { label: "Reported", hint: "Media report the companies have not confirmed." },
  terminated: { label: "Terminated", hint: "Cancelled after being announced." },
};

export const EVIDENCE: Record<string, { label: string; hint: string; rank: number }> = {
  "press release": { label: "Company press release", hint: "Stated in a press release issued by a party to the deal.", rank: 0 },
  article: { label: "News article", hint: "Stated in the body of a news article we could read.", rank: 1 },
  summary: { label: "News summary", hint: "Stated in a news service's summary of a paywalled article.", rank: 2 },
  headline: { label: "Headline only", hint: "Only the headline was readable; the article is paywalled.", rank: 3 },
};
