#!/usr/bin/env python3
"""Bring the ledger up to date: from where the last completed run ended to
today, a month at a time. Search the news, read the articles we can, have
Claude extract the deals, merge them, rebuild the map.

    python3 run.py                     # continue from the last completed run (first time: config "start")
    python3 run.py --until 2025-01-31  # stop at a date (try a month first)
    python3 run.py --no-claude         # search and read only
    python3 run.py --topic cooling     # only that topic's searches, from config "start" (own coverage)

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


def wait_for_reset(e, log):
    """Sleep until the Claude plan's usage limit resets (plus a margin), or
    30 minutes when the message gave no time; the caller then retries, and a
    limit still in force simply comes back here."""
    margin = dt.timedelta(minutes=3)
    now = dt.datetime.now().astimezone()
    if e.resets_at and e.resets_at > now:
        until = e.resets_at + margin
        why = f"resets at {e.resets_at.strftime('%a %H:%M')}"
    else:
        until = now + dt.timedelta(minutes=30)
        why = "no reset time in the message, checking again in 30 min"
    log(f"  Claude usage limit reached ({e.message[:160]}). {why}; waiting until {until.strftime('%a %H:%M')}")
    log.set(f"waiting for the Claude usage limit to reset, until {until.strftime('%a %H:%M')}")
    # Short sleeps against the wall clock: a Mac that sleeps through the
    # reset time wakes up and carries on at once.
    while dt.datetime.now().astimezone() < until:
        time.sleep(min(60, max(1, (until - dt.datetime.now().astimezone()).total_seconds())))
    log("  limit wait over, retrying the batch")


def queries_for(cfg, topic=None):
    """(query, loose) pairs. A normal run asks every search, topics included;
    --topic asks only that topic's. Topic searches are loose: a deal headline
    without an amount still counts (cooling M&A rarely states one)."""
    press = lambda qs: [f"{q} {cfg['press_sites']}" for q in qs]
    topics = cfg.get("topic_searches", {})
    if topic:
        t = topics[topic]
        return [(q, True) for q in t.get("news", []) + press(t.get("press", []))]
    out = [(q, False) for q in cfg["news_searches"] + press(cfg.get("press_searches", []))]
    for t in topics.values():
        out += [(q, True) for q in t.get("news", []) + press(t.get("press", []))]
    return out


def run_window(a, b, cfg, db, cdoc, ddoc, log, use_claude, topic=None):
    run_id = f"{b.isoformat()}-{dt.datetime.now().strftime('%H%M')}" + (f"-{topic}" if topic else "")
    report = {"id": run_id, "since": a.isoformat(), "until": b.isoformat(), "completed": False,
              **({"topic": topic} if topic else {}),
              "started": dt.datetime.now().isoformat(timespec="seconds"), "searched": 0, "candidates": 0,
              "read": {}, "new_deals": [], "updated_deals": [], "new_companies": [], "rejected": [], "errors": []}
    label = f"{a} → {b}"
    log(f"=== {label}  (run {run_id})")

    # 1. search
    queries = queries_for(cfg, topic)
    added = 0
    for n, (q, loose) in enumerate(queries, 1):
        log.set(f"{label}: searching {n}/{len(queries)}")
        for it in news.google_search(q, a, b, log):
            it["candidate"] = news.is_candidate(it["title"], it["summary"], loose)
            added += store.add_item(db, it)
            report["searched"] += 1
        time.sleep(news.PAUSE)
    key = env_key("FINNHUB_API_KEY")
    if key and not topic and (b - a).days <= 21 and a >= dt.date.today() - dt.timedelta(days=360):
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
        attempt = 0
        while attempt < 2:
            try:
                result = extract.call_claude(extract.build_prompt(batch, cdoc["companies"], cdoc["layers"], ddoc["deals"]),
                                             cfg.get("model", "sonnet"))
                break
            except extract.UsageLimit as e:
                # Not a failure: wait for the plan's limit to reset, then
                # send the same batch again. Does not use up an attempt.
                wait_for_reset(e, log)
                log.set(f"{label}: Claude batch {k + 1}/{nb} (retrying after the limit reset)")
            except Exception as e:
                attempt += 1
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


def refresh_fundamentals(log):
    """SEC financials (revenue, EPS, capex) for the map, at most once a week.
    Never stops a run: without SEC_USER_AGENT or the network it just says so."""
    import fundamentals
    try:
        fundamentals.main(["--if-older", "7"])
    except SystemExit as e:
        log(f"Fundamentals not refreshed: {e}")
    except Exception as e:
        log(f"Fundamentals not refreshed: {type(e).__name__}: {e}")


def export_public(log):
    """The website's data (web/public/data.json): no amounts, rewritten summaries.
    Never stops a run."""
    import export
    try:
        export.main([])
    except SystemExit as e:
        log(f"Website data not exported: {e}")
    except Exception as e:
        log(f"Website data not exported: {type(e).__name__}: {e}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", help="YYYY-MM-DD; default: where the last completed run ended")
    ap.add_argument("--until", help="YYYY-MM-DD; default: today")
    ap.add_argument("--no-claude", action="store_true", help="search and read articles only")
    ap.add_argument("--topic", help="run only this config topic_searches group (e.g. cooling), with its own coverage")
    a = ap.parse_args()

    log = Logbook(dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")).start()
    news.on_wait = log
    cfg = load(os.path.join(ROOT, "config.json"))
    cdoc = load(os.path.join(DATA, "companies.json"))
    ddoc = load(os.path.join(DATA, "deals.json"))
    os.makedirs(RUNS, exist_ok=True)
    db = store.connect()
    if a.topic and a.topic not in cfg.get("topic_searches", {}):
        log(f"Unknown topic {a.topic!r}; config topic_searches has: {', '.join(cfg.get('topic_searches', {})) or 'none'}")
        return 1

    # Coverage is per topic: a normal run's timeline ignores topic runs, and a
    # topic run continues from its own last completed month.
    done = [r for r in completed_runs() if r.get("topic") == a.topic]
    if a.since:
        since = dt.date.fromisoformat(a.since)
    else:
        # The end of unbroken coverage from config "start": a run done out of
        # order (a test week, say) does not make the backfill skip the gap.
        end = dt.date.fromisoformat(cfg["start"]) - dt.timedelta(days=1)  # last day covered
        for r in sorted(done, key=lambda r: r["since"]):
            if dt.date.fromisoformat(r["since"]) <= end + dt.timedelta(days=1):
                end = max(end, dt.date.fromisoformat(r["until"]))
        since = end + dt.timedelta(days=1)  # the day after, not the last day again
    until = dt.date.fromisoformat(a.until) if a.until else dt.date.today()
    if since > until:
        log(f"Nothing to do: already up to {since - dt.timedelta(days=1)}")
        return 0
    windows = list(months(since, until))
    log(f"Log file: {log.path}")
    log(f"Window {since} → {until}: {len(windows)} month(s). Last completed run: {done[-1]['id'] if done else 'none'}")

    code = 0
    try:
        for n, (wa, wb) in enumerate(windows, 1):
            log(f"Month {n}/{len(windows)}")
            run_window(wa, wb, cfg, db, cdoc, ddoc, log, not a.no_claude, a.topic)
            if not a.no_claude:
                build.build()
    except news.RateLimited as e:
        log(f"STOPPED: {e}. Progress is kept; run again later to continue.")
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
            refresh_fundamentals(log)
            export_public(log)
            log(f"Finished. Map: {build.build()}")
        log.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
