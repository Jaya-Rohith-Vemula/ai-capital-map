# AI Capital Map

Who is funding whom in the AI build-out: labs, hyperscalers, neoclouds, chips,
memory, foundries, power. An interactive, zoomable map that a weekly run keeps
up to date from the news.

```bash
./backfill.sh               # bring the ledger up to date, in the background, Mac kept awake
tail -f logs/<latest>.log   # watch it: timestamped, with a heartbeat every minute
python3 build.py --open     # just redraw and open out/map.html
```

No schedule: each run continues from where the last completed one ended
(first time: 2024-11-01, from `config.json`), a month at a time, and resumes
if it stops. It searches Google News, reads every article it can (paywalled
ones stay headline-only), and Claude extracts the deals. Needs Python 3.9+
and the `claude` CLI signed in; `FINNHUB_API_KEY` in `.env` is optional and
only used for short windows.

In the map: scroll or pinch to zoom, drag to pan, `/` to search, `F` to fit.
Click a company for what it does, its money in and out, its financials from
SEC filings (revenue, EPS, capex) and live price and P/E from TradingView; click an arrow for
the deal and its sources. "Highlight changes since" makes the latest run's
additions glow. Dashed arrows are seed deals not yet confirmed by a news item.

Every command, what it does and when to use it: `COMMANDS.md`. Design and data model: `docs/DESIGN.md`. Holdings to highlight, searches and
model: `config.json`. Every run is a commit-able change to `data/` plus a
`runs/<id>.json` record, so `git log -p data/deals.json` is the history.

The public website is a React app in `web/` (`cd web && npm run dev`), built
for Vercel from `web/public/data.json`, which `python3 export.py` writes:
relationships, kinds of deal, dates and sources, but no deal amounts.
