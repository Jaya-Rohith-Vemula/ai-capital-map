# AI Capital Map

Who is funding whom in the AI build-out: labs, hyperscalers, neoclouds, chips,
memory, foundries, power. An interactive, zoomable map that a weekly run keeps
up to date from the news.

```bash
python3 run.py              # weekly: news since the last run → Claude extracts deals → map
python3 build.py --open     # just redraw and open out/map.html
python3 run.py --dry-run    # see what a run would add, write nothing
python3 run.py --strict --since 2026-05-01   # long backfill, headline must carry $B or GW
```

Needs Python 3.9+, the `claude` CLI signed in (extraction runs on the Claude
Code plan, `claude -p`), and `FINNHUB_API_KEY` in `.env` (Google News needs no
key). A weekly run reads ~8,000 headlines, filters to several hundred, and
sends them to Claude in batches of 120: expect 15–30 minutes.

In the map: scroll or pinch to zoom, drag to pan, `/` to search, `F` to fit.
Click a company for what it does and its money in and out; click an arrow for
the deal and its sources. "Highlight changes since" makes the latest run's
additions glow. Dashed arrows are seed deals not yet confirmed by a news item.

Design and data model: `docs/DESIGN.md`. Holdings to highlight, searches and
model: `config.json`. Every run is a commit-able change to `data/` plus a
`runs/<id>.json` record, so `git log -p data/deals.json` is the history.
