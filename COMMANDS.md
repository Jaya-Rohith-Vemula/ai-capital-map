# Commands

Every command runs from the repo folder:

```bash
cd ~/Documents/ai-capital-map
```

## Update the ledger (the main command)

| Command | What it does |
| --- | --- |
| `./backfill.sh` | **Use this one.** Runs `run.py` in the background, keeps the Mac awake while it runs (`caffeinate -i`), and prints the log file to follow. Picks up where the last completed run ended, a month at a time, up to today. Safe to run any time: if everything is up to date it says so and stops. |
| `./backfill.sh --until 2025-01-31` | The same, but stop at a date. Any `run.py` option below works here too. |
| `python3 run.py` | The same as `./backfill.sh`, but in the foreground: the log prints to the terminal and it stops if you close the terminal. The Mac is not kept awake. |
| `python3 run.py --until 2025-01-31` | Stop at a date instead of today. Useful for trying one month. |
| `python3 run.py --since 2026-10-01` | Start from a given date instead of where coverage ends. A run that starts out of order does not move the main timeline forward past a gap. |
| `python3 run.py --no-claude` | Search and read the articles only, with no Claude. Fills `store/news.db` without using the Claude plan. Running again later without the flag extracts them. |

What a run does, month by month: search Google News (plus Finnhub for windows of 3 weeks or less) → filter to deal headlines → read the articles we are allowed to → Claude extracts the deals → check and merge into `data/deals.json` → write `runs/<month>.json` → redraw the map. Details: `docs/DESIGN.md`.

If it stops (Google rate limit, an error, Ctrl-C), run `./backfill.sh` again: it continues from the unfinished month without fetching or extracting anything twice. If the Claude plan's 5-hour or weekly limit is reached, it waits for the reset by itself and carries on.

## Watch a run

```bash
# follow the latest log live (Ctrl-C stops watching, not the run)
tail -f "logs/$(ls -t logs | grep '\.log$' | head -1)"

# one line per month started and finished, plus any stop, sleep gap or Claude limit wait
grep -E "=== |done:|STOPPED|resumed|limit" "logs/$(ls -t logs | grep '\.log$' | head -1)"

# every new deal found in the latest run
grep "    + " "logs/$(ls -t logs | grep '\.log$' | head -1)"
```

Every log line is timestamped, and a `♥ alive:` line each minute says what the run is doing.

| Command | What it does |
| --- | --- |
| `pgrep -fl "[Pp]ython.* run.py"` | Is a run going? Prints its process id, or nothing. |
| `pkill -INT -f "[Pp]ython.* run.py"` | Stop a background run cleanly (the same as Ctrl-C): progress is kept, and `./backfill.sh` resumes it. |
| `ls runs/` | The completed runs, one per month (`<month end>-<HHMM>.json`). Only completed months are written. |

In the log, `resumed after a N min gap` means the laptop was asleep and nothing ran in between. Keep the Mac on the charger: a closed lid on battery sleeps even with `caffeinate`.

## The map

| Command | What it does |
| --- | --- |
| `python3 build.py --open` | Redraw `out/map.html` from the ledger and open it. No news, no Claude, a second or two. |
| `python3 build.py` | Redraw without opening. Runs do this after every month anyway. |
| `open out/map.html` | Open the last drawn map. |

In the map: scroll or pinch to zoom, drag to pan, `/` to search, `F` to fit everything, click a company or an arrow for details.

## Company financials (SEC filings)

| Command | What it does |
| --- | --- |
| `python3 fundamentals.py` | Refresh `data/fundamentals.json`: revenue, net income, diluted EPS, capex and operating cash flow (last 5 fiscal years, last 12 quarters) for every listed company that files with the SEC. About a minute. Runs do this by themselves once a week. |
| `python3 fundamentals.py NVDA TSM` | Refresh just these tickers, keep the rest. |

Needs `SEC_USER_AGENT="Your Name you@example.com"` in `.env`: SEC refuses requests without a contact. Prices, P/E and market cap are not from here: the map loads them live from TradingView when you open a company (needs the internet).

## The website (web/)

| Command | What it does |
| --- | --- |
| `python3 export.py` | Write `web/public/data.json`, the site's data: no deal amounts, summaries rewritten without them (by Claude, cached in `data/public_text.json`, only new or changed ones), no unverified seed deals, sources as publisher + date + link. Runs do this by themselves at the end. |
| `python3 export.py --no-claude` | The same with cached rewrites only; stops if one is missing. |
| `cd web && npm install` | Once, to install the site's packages. |
| `cd web && npm run dev` | Run the site locally with live reload: http://localhost:5173 |
| `cd web && npm run build` | Build the site into `web/dist` (what Vercel serves). |

Deploying on Vercel: import the repo, set **Root Directory** to `web` (framework Vite, the rest is in `web/vercel.json`). Each push redeploys; the data is `web/public/data.json`, so committing a run's changes updates the site.

## Look at the data

| Command | What it does |
| --- | --- |
| `python3 -c "import json; d=json.load(open('data/deals.json'))['deals']; print(len(d), 'deals')"` | How many deals are in the ledger. |
| `grep -l '"IREN"' runs/*.json` | Which runs touched a company (swap in any id). |
| `sqlite3 store/news.db "select fetch, count(*) from items where candidate=1 group by fetch"` | How many candidate articles were read, blocked, failed or too short. |
| `sqlite3 store/news.db "select published, source, title from items where title like '%Nebius%' order by published"` | Every stored headline mentioning a name. |
| `sqlite3 store/news.db "select text from items where title like '%IREN%Microsoft%' limit 1"` | The stored article text of one story. |
| `git log -p data/deals.json` | How the ledger changed over time. |

## Change what it looks for

| File | What to edit |
| --- | --- |
| `data/companies.json` | Add a company (id, name, ticker, layer, what it does, aliases). Edit only while no run is going: a run rewrites this file after every batch. |
| `config.json` | `holdings` (gold ring on the map), `news_searches` and `press_searches` (what Google is asked), `start` (where coverage begins), `model`, `batch_size`. |
| `.env` | `FINNHUB_API_KEY`: optional, used only for short windows. `SEC_USER_AGENT`: your name and email, for `fundamentals.py`. Gitignored. |
| `data/companies.json` `market` | TradingView symbol for a company listed outside the US or whose ticker means something else there (`"ASX:NXT"`); `false` hides the live market panel. US listings need nothing. |

## Planned, not built yet

- `python3 run.py --company <id> --since <date>`: search for one company's deals specifically, and follow new listed companies first seen in a deal of $1B or more automatically (see `docs/DESIGN.md`, "Planned: follow new companies").

## Where things are

| Path | What | In git |
| --- | --- | --- |
| `data/deals.json`, `data/companies.json` | The ledger and the companies | yes |
| `data/fundamentals.json` | SEC financials per listed company | yes |
| `data/public_text.json` | Deal summaries rewritten without amounts, for the site | yes |
| `web/` | The React site (Vite); `web/public/data.json` is its data | yes (not `node_modules`, `dist`) |
| `runs/` | One record per completed month or run | yes |
| `store/news.db` | Every headline, its URL, fetch result and article text | no, it stays on this laptop (publishers' text) |
| `logs/` | Run logs | no |
| `out/map.html` | The drawn map | no, redraw any time |
| `docs/DESIGN.md` | How it all works and why | yes |
