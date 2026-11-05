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

## Limits

- Paywalled-only stories stay `headline` evidence until a readable copy or a
  press release turns up.
- Google News coverage thins for older months.
- Private companies have no SEC filings; for listed ones, 8-K material
  agreements would be a stronger primary source (not built).

## The map

Rebuilt after every month. To be redesigned: the current one works (zoom,
pan, search, filters, what's new) but is cluttered.
