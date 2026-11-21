# AI Capital Map: design

Who is paying whom to build AI: labs, hyperscalers, neoclouds, chips, memory,
foundries, power. One script brings a ledger of deals up to date from the
news and redraws an interactive map of it.

Research only. Nothing here trades, and nothing in portfolio-pilot reads it;
that is why it lives in its own repo.

## Running it

```
./backfill.sh             # run.py in the background, Mac kept awake (caffeinate -i)
python3 run.py            # the same, in the foreground
python3 run.py --until 2025-01-31   # stop early, e.g. to try one month
python3 build.py --open   # redraw out/map.html from the ledger, no news, no Claude
tail -f logs/<latest>.log # follow a run
```

There is no schedule. A run always continues from where coverage ends: from
`config.json` `start` (2024-11-01), the end of the unbroken chain of completed
runs. Run it after a week or after three months; it catches up either way.

## A run

The window is cut into calendar months. For each month:

1. **Search.** Google News RSS for each query in `config.json`: the deal
   searches, plus press-release searches limited to PR Newswire and
   GlobeNewswire (primary sources, and readable). Long windows use
   `after:/before:`; Google returns ~100 results per search, hence months.
   Finnhub company news is added only for short windows (≤ 3 weeks, within its
   1-year free history): its summaries are written from the full article, so
   they help most when the article is paywalled.
2. **Filter.** A headline is a candidate if it names money or scale *and* a
   deal word, and is not commentary (price targets, "if you invested", ETF
   flows...).
3. **Read.** For each candidate: resolve Google's redirect to the publisher
   URL, fetch the page, keep the paragraphs. Outlets known to refuse scripts
   (Bloomberg, Reuters, WSJ, FT, Barron's, Forbes, Business Wire) are not
   asked; a domain that answers 401/403 three times is not asked again. We do
   not try to get around a paywall.
4. **Extract.** `claude -p` on the Claude Code plan, tools off, structured
   output, 25 items a batch. Each item: title, Finnhub summary if any, and the
   article's opening and money/deal paragraphs (≤ 3,500 chars).
5. **Check and merge** (`extract.py`). The quote Claude gives must occur in the
   item, and where it occurs is the deal's **evidence**: `press release`,
   `article`, `summary` or `headline`. Both parties must resolve to known
   companies or ones the same response defines. A repeat (`same_as`) adds the
   source, keeps the best evidence, and lets better-evidenced or newer terms
   replace the old ones (kept in `history`).
6. **Record.** `runs/<month end>-<HHMM>.json` is written, `completed: true`,
   only when the month is fully done. The ledger is saved after every batch.

### Stopping and resuming

Google rate limiting, Claude failing twice, Ctrl-C or a crash stop the run
cleanly. Nothing done is lost: searched items, fetched articles and extracted
flags are in the store, deals in the ledger. The next run starts at the same
month; searches repeat (deduplicated), fetched articles are not fetched
again, extracted items are not sent again.

### The log

`logs/<started>.log`, every line timestamped: each search, each article read
(read / blocked / failed / short), each batch, each deal. A heartbeat every
minute repeats what it is doing. A sleeping Mac freezes the process, so a
heartbeat that arrives late says "resumed after N min gap: the laptop was
probably asleep". `backfill.sh` runs under `caffeinate -i` to prevent idle
sleep; a closed lid on battery still sleeps.

## Data

| where | what | in git |
| --- | --- | --- |
| `data/companies.json` | id, name, ticker, layer, what it does, aliases | yes |
| `data/deals.json` | the ledger, one row per deal | yes |
| `runs/*.json` | one per month or run: window, counts, new/updated deals, rejections | yes |
| `store/news.db` | SQLite: every headline, real URL, fetch outcome, article text | **no**: publishers' text stays local |
| `logs/` | run logs | no |
| `config.json` | start date, searches, holdings, model, batch size | yes |

A deal: `from` pays `to` (investor → company, customer → provider, buyer →
supplier). Types: `equity`, `compute`, `chips`, `lease`, `power`,
`financing`, `acquisition`, `partnership`. Status: `announced` (signed,
confirmed), `loi` (letter of intent, MOU, milestone-based "up to"),
`reported` (media, unconfirmed), `completed`, `terminated`.

**Seed deals** (`origin: seed`) came from Claude's training knowledge (to mid
2026), not a fetched article: unverified until a news item matches them.

## Planned: follow new companies (decided 2026-11-05, not built)

Adding a company today only adds it to the list Claude matches against;
nothing searches for it, so its smaller or earlier deals are missed. Planned:

- When a run adds a company, queue a **targeted search** for it (company-name
  queries such as "<name> deal", "<name> agreement", "<name> invests",
  month by month from `start`), then read and extract as usual. Articles
  already in `store/news.db` that mention it are re-checked without
  downloading again.
- Followed only if **all** hold:
  - **it has a stock ticker** (listed, so investable);
  - **size threshold**: first seen in a deal of about **$1B or more**;
  - **depth 1**: it was added by the main searches. Companies a targeted
    search finds are added but not followed, so A → B → C cannot snowball.
- A targeted search is recorded as its own run (`kind: follow`), outside the
  unbroken coverage chain that ordinary runs continue from.
- The same mechanism gives `run.py --company <id> --since <date>` by hand.

## Company financials

Clicking a listed company shows two things:

- **Financials · SEC filings** (`fundamentals.py` → `data/fundamentals.json`):
  revenue, net income, diluted EPS, capex, operating cash flow, for the last
  5 fiscal years and 12 quarters, from data.sec.gov companyfacts (XBRL as
  filed). 10-Qs report cash flows year to date and there is no Q4 filing, so
  quarters are derived as differences of year-to-date figures. Capex is cash
  paid for property and equipment; finance leases are not in it. Covers US
  filers and the foreign ones filing 20-F/40-F (TSMC, ASML, Arm...), in their
  reporting currency. US government data: fine to publish. SEC's name for the
  ticker must match ours, since tickers get reused (NXT is NEXTDC on the ASX,
  Nextpower on Nasdaq). Refreshed weekly at the end of a run.
- **Market · live**: TradingView's free embeddable widgets (price, P/E, EPS,
  market cap, valuation and statement summary), loaded in the browser. Their
  licence allows public embedding, which free API keys (Finnhub, FMP, Alpha
  Vantage, Yahoo) do not. Symbol: `market` in `companies.json` if set, else
  the SEC exchange + ticker. Korean (KRX) prices are not shown in embeds;
  their financials are.

The overview ranks the biggest capex spenders over the last four quarters
(US dollar filers).

## The public site (web/)

A static React app (Vite, Cytoscape for the graph) meant for Vercel; it reads
`web/public/data.json`, which `export.py` writes from the ledger. No backend.

What it publishes, decided 2026-11-19: **no deal amounts anywhere.** They
come from news reports read by Claude, not official filings; reported figures
are often "up to" ceilings or multi-year totals, and one wrong number would
cost the map its credibility. The ledger keeps them. Deal summaries are
rewritten by Claude without amounts (checked by a money regex before use).
Unverified seed deals are left out. Sources are publisher, date and link
only: headlines carry amounts and quotes are the publishers' text. SEC
financials (official) and TradingView widgets are shown.

The site: graph by layer (or a force "web"), hover and click to focus a
company or deal, filters by deal type, layer, status and "press release
only", a timeline from Nov 2024 that can play month by month, search (`/`),
deep links (`#/c/NVDA`, `#/d/d006`), light and dark themes, phone layout.

## Planned: confirm deals from SEC filings (not built)

EDGAR full-text search (efts.sec.gov, free, 2001+) finds a counterparty's
name in a company's own filings: 8-K material agreements and their press
release exhibits, contracts filed as 10-Q/10-K exhibits, customer
concentration and commitment notes, S-1s, 13D/13G stakes. Tried on IREN →
Microsoft: the 8-K the day of the announcement and the contract itself (EX-10.3
to a 10-Q). 224 of 268 public deals have at least one SEC filer. Plan: per
deal, search each filer party's filings from a month before the deal date for
the other party's name and aliases; Claude checks the matching passage
describes this deal; a match becomes `evidence: "SEC filing"` with the link,
the strongest evidence, and a filter on the site.

## Limits

- Paywalled-only stories stay `headline` evidence until a readable copy or a
  press release turns up.
- Google News coverage thins for older months.
- Private companies have no SEC filings; for listed ones, 8-K material
  agreements would be a stronger primary source (not built).

## The map

Rebuilt after every month. To be redesigned: the current one works (zoom,
pan, search, filters, what's new) but is cluttered.
