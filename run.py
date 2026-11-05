#!/usr/bin/env python3
"""Bring the ledger up to date: from where the last completed run ended to
today, a month at a time. Search the news, read the articles we can, have
Claude extract the deals, merge them, rebuild the map.

    python3 run.py                     # continue from the last completed run (first time: config "start")
    python3 run.py --until 2025-01-31  # stop at a date (try a month first)
    python3 run.py --no-claude         # search and read only

Each month is its own run record in runs/, written only when the month is
fully done, so a run that stops (rate limit, error, Ctrl-C) resumes where it
left off. Everything is logged to logs/, with a heartbeat each minute.
See docs/DESIGN.md.
"""

import argparse
import calendar
import datetime as dt
import json
import os
import sys
import time

import build
import extract
import news
import store
from logbook import Logbook

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
RUNS = os.path.join(ROOT, "runs")


def load(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def env_key(name):
    if os.environ.get(name):
        return os.environ[name]
    try:
        with open(os.path.join(ROOT, ".env")) as f:
            for line in f:
                k, _, v = line.strip().partition("=")
                if k == name:
                    return v.strip().strip('"')
    except FileNotFoundError:
        pass
    return None


def completed_runs():
    if not os.path.isdir(RUNS):
        return []
    rs = [load(os.path.join(RUNS, f)) for f in sorted(os.listdir(RUNS)) if f.endswith(".json")]
    return [r for r in rs if r and r.get("completed")]


def months(since, until):
    """[since, until] cut at month ends."""
    a = since
    while a <= until:
        end = dt.date(a.year, a.month, calendar.monthrange(a.year, a.month)[1])
        b = min(end, until)
        yield a, b
        a = b + dt.timedelta(days=1)


class Stop(Exception):
    pass


def run_window(a, b, cfg, db, cdoc, ddoc, log, use_claude):
    run_id = f"{b.isoformat()}-{dt.datetime.now().strftime('%H%M')}"
    report = {"id": run_id, "since": a.isoformat(), "until": b.isoformat(), "completed": False,
              "started": dt.datetime.now().isoformat(timespec="seconds"), "searched": 0, "candidates": 0,
              "read": {}, "new_deals": [], "updated_deals": [], "new_companies": [], "rejected": [], "errors": []}
    label = f"{a} → {b}"
    log(f"=== {label}  (run {run_id})")

    # 1. search
    queries = cfg["news_searches"] + [f"{q} {cfg['press_sites']}" for q in cfg.get("press_searches", [])]
    added = 0
    for n, q in enumerate(queries, 1):
        log.set(f"{label}: searching {n}/{len(queries)}")
        for it in news.google_search(q, a, b, log):
            it["candidate"] = news.is_candidate(it["title"], it["summary"])
            added += store.add_item(db, it)
            report["searched"] += 1
        time.sleep(news.PAUSE)
    key = env_key("FINNHUB_API_KEY")
    if key and (b - a).days <= 21 and a >= dt.date.today() - dt.timedelta(days=360):
        tickers = [c["ticker"] for c in cdoc["companies"] if c.get("ticker") and "." not in c["ticker"]]
        for n, t in enumerate(tickers, 1):
            log.set(f"{label}: Finnhub {n}/{len(tickers)} ({t})")
            try:
                for it in news.finnhub_news(t, a, b, key):
                    it["candidate"] = news.is_candidate(it["title"], it["summary"])
                    added += store.add_item(db, it)
                    report["searched"] += 1
            except Exception as e:
                log(f"  finnhub {t}: {e}")
    db.commit()
    rows = db.execute("SELECT * FROM items WHERE candidate = 1 AND published BETWEEN ? AND ? ORDER BY published",
                      (a.isoformat(), b.isoformat())).fetchall()
    report["candidates"] = len(rows)
    log(f"  searched: {report['searched']} headlines ({added} new to the store), {len(rows)} candidates")

    # 2. read the articles
    pending = [r for r in rows if r["fetch"] == "pending"]
    for n, r in enumerate(pending, 1):
        log.set(f"{label}: reading article {n}/{len(pending)}")
        state = news.read_item(db, r, log)
        log(f"  read {n}/{len(pending)} {state:8} {r['source'][:20]:20} {r['title'][:90]}")
    for r in db.execute("SELECT fetch, COUNT(*) n FROM items WHERE candidate = 1 AND published BETWEEN ? AND ? GROUP BY fetch",
                        (a.isoformat(), b.isoformat())):
        report["read"][r["fetch"]] = r["n"]
    log(f"  articles: {report['read']}")
    if not use_claude:
        return report

    # 3. extract
    todo = db.execute("SELECT * FROM items WHERE candidate = 1 AND published BETWEEN ? AND ? AND extracted IS NULL"
                      " ORDER BY published", (a.isoformat(), b.isoformat())).fetchall()
    size = cfg.get("batch_size", 25)
    nb = (len(todo) + size - 1) // size
    for k in range(nb):
        batch = [dict(r) for r in todo[k * size:(k + 1) * size]]
        log.set(f"{label}: Claude batch {k + 1}/{nb} ({len(batch)} items); {len(report['new_deals'])} new deals so far")
        log(f"  Claude batch {k + 1}/{nb}: {len(batch)} items, {sum(1 for x in batch if x['text'])} with article text")
        result = None
        for attempt in (1, 2):
            try:
                result = extract.call_claude(extract.build_prompt(batch, cdoc["companies"], cdoc["layers"], ddoc["deals"]),
                                             cfg.get("model", "sonnet"))
                break
            except Exception as e:
                log(f"  Claude failed (attempt {attempt}): {e}")
                report["errors"].append(str(e)[:300])
        if result is None:
            raise Stop("Claude failed twice; the rest of this month stays unextracted and is retried next run")
        before = (len(report["new_deals"]), len(report["updated_deals"]))
        extract.merge(result, batch, cdoc["companies"], cdoc["layers"], ddoc["deals"], run_id, report)
        # Ledger first, then mark the items: a crash in between re-sends
        # them, and same_as matching absorbs the repeat.
        save(os.path.join(DATA, "companies.json"), cdoc)
        save(os.path.join(DATA, "deals.json"), ddoc)
        db.executemany("UPDATE items SET extracted = ? WHERE key = ?", [(run_id, x["key"]) for x in batch])
        db.commit()
        by_id = {d["id"]: d for d in ddoc["deals"]}
        names = {c["id"]: c["name"] for c in cdoc["companies"]}
        for i in report["new_deals"][before[0]:]:
            d = by_id[i]
            log(f"    + {names[d['from']]} → {names[d['to']]}  {d['type']}  {d['usd_text']}  {d['status']}  [{d['evidence']}]  {d['date']}")
        for i in report["updated_deals"][before[1]:]:
            d = by_id[i]
            log(f"    ~ {names[d['from']]} → {names[d['to']]}  {d['usd_text']}  now [{d['evidence']}], {len(d['sources'])} sources")

    report["completed"] = True
    report["finished"] = dt.datetime.now().isoformat(timespec="seconds")
    save(os.path.join(RUNS, run_id + ".json"), report)
    log(f"  done: {len(report['new_deals'])} new, {len(report['updated_deals'])} updated, "
        f"{len(report['new_companies'])} new companies, {len(report['rejected'])} rejected")
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", help="YYYY-MM-DD; default: where the last completed run ended")
    ap.add_argument("--until", help="YYYY-MM-DD; default: today")
    ap.add_argument("--no-claude", action="store_true", help="search and read articles only")
    a = ap.parse_args()

    log = Logbook(dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")).start()
    cfg = load(os.path.join(ROOT, "config.json"))
    cdoc = load(os.path.join(DATA, "companies.json"))
    ddoc = load(os.path.join(DATA, "deals.json"))
    os.makedirs(RUNS, exist_ok=True)
    db = store.connect()

    done = completed_runs()
    if a.since:
        since = dt.date.fromisoformat(a.since)
    else:
        # The end of unbroken coverage from config "start": a run done out of
        # order (a test week, say) does not make the backfill skip the gap.
        since = dt.date.fromisoformat(cfg["start"])
        for r in sorted(done, key=lambda r: r["since"]):
            if dt.date.fromisoformat(r["since"]) <= since + dt.timedelta(days=1):
                since = max(since, dt.date.fromisoformat(r["until"]))
    until = dt.date.fromisoformat(a.until) if a.until else dt.date.today()
    if since > until:
        log(f"Nothing to do: already up to {since}")
        return 0
    windows = list(months(since, until))
    log(f"Log file: {log.path}")
    log(f"Window {since} → {until}: {len(windows)} month(s). Last completed run: {done[-1]['id'] if done else 'none'}")

    code = 0
    try:
        for n, (wa, wb) in enumerate(windows, 1):
            log(f"Month {n}/{len(windows)}")
            run_window(wa, wb, cfg, db, cdoc, ddoc, log, not a.no_claude)
            if not a.no_claude:
                build.build()
    except news.RateLimited as e:
        log(f"STOPPED: {e}. Progress is kept; run again in an hour or so to continue.")
        code = 2
    except Stop as e:
        log(f"STOPPED: {e}")
        code = 3
    except KeyboardInterrupt:
        log("STOPPED by Ctrl-C. Progress is kept; run again to continue.")
        code = 130
    except Exception as e:
        log(f"STOPPED on an unexpected error: {type(e).__name__}: {e}")
        raise
    finally:
        db.close()
        if code == 0:
            log(f"Finished. Map: {build.build()}")
        log.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
