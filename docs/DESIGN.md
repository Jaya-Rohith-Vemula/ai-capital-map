# AI Capital Map: design

Who is paying whom to build AI: labs, hyperscalers, neoclouds, chips, memory,
foundries, power. One weekly command reads the news, finds new deals, adds
them to a ledger and redraws an interactive map that highlights what changed
since the last run.

Research only. Nothing here trades, and nothing in portfolio-pilot reads it;
that is why it lives in its own repo.

## The weekly run

```
python3 run.py            # news since the last run → extract → merge → build
python3 build.py          # redraw out/map.html from the ledger, no news, no Claude
```

1. **Fetch.** Finnhub company news for every company with a US ticker
   (`FINNHUB_API_KEY` in `.env`), plus Google News RSS searches from
   `config.json` (they catch private companies: OpenAI, Anthropic, xAI,
   Fluidstack). Window: from the last run's end to now; the first run (or
   `--since`) can backfill.
2. **Filter.** Items already processed (`data/seen.json`) are dropped. The rest
   must mention money or scale (`$`, billion, GW, MW) *and* a deal word
   (invest, stake, contract, agreement, lease, backstop, PPA...). Cheap, and
   keeps the Claude calls small.
3. **Extract.** `claude -p` on the Claude Code plan, tools off, structured
   output (`--json-schema`), in batches. It gets the company list, a compact
   ledger and the items; it returns deals, each pointing at the item it came
   from, with a verbatim quote, and `same_as` when the ledger already holds it.
4. **Check in code.** A deal is rejected unless its quote really occurs in the
   item's title or summary, and both ends resolve to a known company or one the
   same response defines. Rejections are listed in the run record, not dropped
   silently.
5. **Merge.** New deals get `first_seen = run id`. A `same_as` match adds the
   source to the existing deal, marks it `verified` and, if the amount changed,
   keeps the old one in `history` and sets `updated_in = run id`.
6. **Build.** `out/map.html`, one file, works offline (Cytoscape is inlined).

## Data (plain JSON, in git, so `git log` is the history)

| file | what | read by |
| --- | --- | --- |
| `data/companies.json` | id, name, ticker, layer, what it does, aliases | run (matching, prompt), build |
| `data/deals.json` | the ledger: one row per deal | run (dedupe), build |
| `data/seen.json` | hashes of news items already sent to Claude, kept 120 days | run |
| `runs/<id>.json` | per run: window, counts, new/updated deal ids, rejections | build (the "since" picker and the What's new panel) |
| `config.json` | holdings to highlight, news searches, model, batch size | run, build |

A deal: `from` pays `to`. Investor → company for equity; customer → provider
for compute and leases; buyer → supplier for chips and power. Types:
`equity`, `compute`, `chips`, `lease`, `power`, `financing`, `acquisition`,
`partnership`.

**Seed deals** (`origin: seed`) came from Claude's training knowledge (to mid
2026), not a fetched article: drawn dashed and labelled unverified until a
news item matches them.

## The map

- Columns by layer (capital → labs → hyperscalers → neoclouds → servers →
  chips → memory → foundry → power), or a force layout.
- Wheel or pinch to zoom, drag to pan, `+ / − / fit` buttons. Labels shrink
  away when zoomed out so a big graph stays readable.
- Arrow width grows with the dollar amount (log scale), colour is the deal
  type, dashed means unverified seed.
- Click a company: what it does, money in and out, every deal with sources.
  Click an arrow: the deal, the quote and the links.
- "Since" picks a past run; deals new or changed after it glow, and the What's
  new panel lists them.
- Holdings in `config.json` get a gold ring.

## Not yet

- SEC 8-K material agreements (needs a User-Agent with a real contact).
- A money-flow (Sankey) view between layers.
- Full article text: extraction reads the headline and summary only, so an
  amount that is only in the body is missed.
