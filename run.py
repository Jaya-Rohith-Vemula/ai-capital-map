#!/usr/bin/env python3
"""Weekly run: fetch news since the last run, extract deals with Claude,
merge them into data/deals.json, record the run, rebuild out/map.html.

    python3 run.py                     # since the last run (first run: config first_run_days)
    python3 run.py --since 2026-06-01  # backfill from a date
    python3 run.py --dry-run           # fetch, filter, extract, print; write nothing
    python3 run.py --no-claude         # fetch and filter only, to see what would be sent

Standard library only. Claude runs through `claude -p` on the Claude Code plan.
See docs/DESIGN.md.
"""

import argparse
import datetime as dt
import email.utils
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
RUNS = os.path.join(ROOT, "runs")
UA = "Mozilla/5.0 (compatible; ai-capital-map/1.0)"
SEEN_KEEP_DAYS = 120
TYPES = ["equity", "compute", "chips", "lease", "power", "financing", "acquisition", "partnership"]
STATUSES = ["announced", "reported", "completed", "terminated"]

# Both must match: money or scale, and a deal verb. Cheap, and keeps the
# Claude batches to items that could actually hold a deal.
MONEY = re.compile(r"\$\s?\d|\bbillion\b|\bbn\b|\bmillion\b|\bGW\b|gigawatt|megawatt|\bMW\b|\bstake\b|\bwarrants?\b", re.I)
BIG = re.compile(r"\$\s?\d[\d.,]*\s?(?:billion|bn|B|trillion|T)\b|\d\s?(?:GW|gigawatts?)\b", re.I)
# Titles that are commentary, not news of a deal. The same deal is nearly
# always also reported under a plain headline, so dropping these loses little.
NOISE = re.compile(r"price target|\bmaintains\b|reiterat|\bupgrades?\b|\bdowngrades?\b|if you(?: had)? invested|"
                   r"should you buy|\bbuy\?|fairly valued|\bvaluation check|undervalued|overvalued|no-brainer|millionaire|"
                   r"stocks? to (?:buy|watch|own)|what to watch|\bvs\.? |\bvs\b|motley|\bdividend\b|"
                   r"(?:shares|stock) (?:rise|rises|fall|falls|jump|jumps|soar|soars|drop|drops|slide|slides|surge|surges)|"
                   r"\bETFs?\b|\bSPDR\b|\biShares\b|would be worth|worth (?:by|today)|per month|net buying|"
                   r"\bearnings (?:call|preview)|\bQ[1-4] (?:earnings|results)|options activity|unusual options|"
                   r"\bETFs?\b|\b(?:sells|buys) \$[\d.,]+ (?:million|billion)|worth (?:by|today|this much)|"
                   r"\$[\d,]+ investment in|\$[\d,]+ invested|per month|fair value", re.I)
DEAL = re.compile(r"invest|stake|\bdeal\b|contract|agreement|partner|supply|\border|acquir|purchas|\bbuy|lease|backstop|financ|\bloan|warrant|offtake|\bPPA\b|power purchase|commit|capacity|\bsigns?\b|\binks?\b|\bfund", re.I)


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


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def item_key(title, url):
    # Same story from two feeds usually shares a title, not a URL.
    return hashlib.sha1(norm(title).encode()).hexdigest()[:16] if title else hashlib.sha1(url.encode()).hexdigest()[:16]


# ---------- fetch ----------

def finnhub_range(ticker, a, b, key, log):
    q = urllib.parse.urlencode({"symbol": ticker, "from": a.isoformat(), "to": b.isoformat(), "token": key})
    rows = json.loads(http_get("https://finnhub.io/api/v1/company-news?" + q))
    time.sleep(1.1)  # free tier: 60 calls a minute
    # Finnhub returns at most ~250 rows per call, newest first: a full page
    # means older items were cut off, so split the window and ask again.
    if len(rows) >= 240 and a < b:
        mid = a + (b - a) // 2
        return finnhub_range(ticker, a, mid, key, log) + finnhub_range(ticker, mid + dt.timedelta(days=1), b, key, log)
    return rows


def fetch_finnhub(companies, since, until, key, log):
    items = []
    tickers = [c for c in companies if c.get("ticker") and "." not in c["ticker"]]
    for i, c in enumerate(tickers):
        try:
            rows = finnhub_range(c["ticker"], since, until, key, log)
        except Exception as e:  # one bad ticker must not sink the run
            log(f"  finnhub {c['ticker']}: {e}")
            rows = []
        for r in rows:
            items.append({
                "title": r.get("headline", ""), "summary": r.get("summary", ""),
                "url": r.get("url", ""), "source": r.get("source", ""),
                "published": dt.datetime.fromtimestamp(r.get("datetime", 0), dt.timezone.utc).date().isoformat(),
                "feed": "finnhub:" + c["ticker"],
            })
        log(f"  finnhub {c['ticker']:6} {len(rows):4} items  ({i + 1}/{len(tickers)})")
    return items


def fetch_google_news(queries, since, log):
    items = []
    days = max(1, (dt.date.today() - since).days)
    for q in queries:
        url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
            {"q": f"{q} when:{days}d", "hl": "en-US", "gl": "US", "ceid": "US:en"})
        try:
            root = ET.fromstring(http_get(url))
        except Exception as e:
            log(f"  google '{q}': {e}")
            continue
        n = 0
        for it in root.iter("item"):
            pub = it.findtext("pubDate")
            try:
                day = email.utils.parsedate_to_datetime(pub).date()
            except Exception:
                day = dt.date.today()
            if day < since:
                continue
            desc = re.sub(r"<[^>]+>", " ", it.findtext("description") or "")
            items.append({
                "title": it.findtext("title") or "", "summary": desc.strip(),
                "url": it.findtext("link") or "", "source": it.findtext("source") or "Google News",
                "published": day.isoformat(), "feed": "google:" + q,
            })
            n += 1
        log(f"  google  {n:4} items  '{q}'")
        time.sleep(1.0)
    return items


# ---------- extract ----------

SCHEMA = {
    "type": "object",
    "properties": {
        "deals": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "item": {"type": "integer", "description": "number of the news item this deal comes from"},
                "from": {"type": "string", "description": "company id that pays, invests or buys"},
                "to": {"type": "string", "description": "company id that receives the money or supplies"},
                "type": {"type": "string", "enum": TYPES},
                "usd": {"type": ["number", "null"], "description": "headline US dollar value, null if none is stated"},
                "usd_text": {"type": "string", "description": "short label: '$9.7B', 'up to $100B', '1.2 GW'"},
                "date": {"type": "string", "description": "YYYY-MM-DD or YYYY-MM the deal was announced"},
                "status": {"type": "string", "enum": STATUSES},
                "summary": {"type": "string", "description": "one sentence, plain words"},
                "quote": {"type": "string", "description": "verbatim span from the item's title or summary that states the deal"},
                "same_as": {"type": ["string", "null"], "description": "id of the ledger deal this is, or null if new"},
            },
            "required": ["item", "from", "to", "type", "usd", "usd_text", "date", "status", "summary", "quote", "same_as"],
        }},
        "new_companies": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "UPPERCASE ticker if listed, else UPPERCASE short name"},
                "name": {"type": "string"},
                "ticker": {"type": ["string", "null"]},
                "layer": {"type": "string"},
                "does": {"type": "string", "description": "one sentence: what the company does in the AI build-out"},
            },
            "required": ["id", "name", "ticker", "layer", "does"],
        }},
    },
    "required": ["deals", "new_companies"],
}

SYSTEM = """You extract AI build-out deals from news items for a ledger of who pays whom.

A deal is money or a binding commitment between two named organisations in the AI supply chain: equity investments, compute or cloud contracts, chip or server purchases, data-center leases, power purchase agreements, financing or lease backstops, acquisitions, and named partnerships. "from" pays, invests or buys; "to" receives or supplies.

Rules:
- Use only what the item's title and summary say. Never add amounts, dates or parties from your own knowledge.
- quote must be copied character for character from that item's title or summary.
- Skip analyst opinions, price targets, rumours of talks with no agreement, earnings results, product launches, and generic "spending $X on AI" capex with no counterparty.
- Use existing company ids. If a party is not in the list but clearly belongs in the AI build-out, add it to new_companies (layer must be one of the given layer ids) and use its id. Otherwise skip the deal.
- If the ledger already holds the same deal (same parties, same agreement), set same_as to its id, even when the amount was updated or expanded. An expansion that is announced as a separate new agreement is a new deal.
- One item can give several deals, or none. Most items give none. Return each deal once even if several items report it."""


def build_prompt(batch, companies, layers, deals):
    comp = "\n".join(f"{c['id']}: {c['name']} ({', '.join(c.get('aliases', []))})" for c in companies)
    ledger = "\n".join(f"{d['id']}: {d['from']}->{d['to']} {d['type']} {d.get('usd_text', '')} {d.get('date', '')}: {d['summary']}" for d in deals)
    news = "\n\n".join(f"[{i}] {it['published']} {it['source']}\nTITLE: {it['title']}\nSUMMARY: {it['summary'][:700]}" for i, it in enumerate(batch))
    return (f"LAYERS: {', '.join(l['id'] for l in layers)}\n\nCOMPANIES:\n{comp}\n\nLEDGER:\n{ledger}\n\n"
            f"NEWS ITEMS:\n{news}\n\nReturn the deals these items state.")


def call_claude(prompt, model):
    cmd = ["claude", "-p", "--model", model, "--tools", "", "--no-session-persistence",
           "--output-format", "json", "--system-prompt", SYSTEM, "--json-schema", json.dumps(SCHEMA)]
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=900, cwd=ROOT)
    if r.returncode != 0:
        raise RuntimeError(f"claude exited {r.returncode}: {r.stderr.strip()[:500]}")
    out = json.loads(r.stdout)
    if out.get("is_error") or "structured_output" not in out:
        raise RuntimeError(f"claude: {out.get('subtype')} {str(out.get('result'))[:300]}")
    return out["structured_output"]


# ---------- merge ----------

def merge(result, batch, companies, layers, deals, run_id, report):
    known = {c["id"] for c in companies}
    layer_ids = {l["id"] for l in layers}
    for nc in result.get("new_companies", []):
        nc["id"] = nc["id"].upper()
        if nc["id"] in known:
            continue
        if nc.get("layer") not in layer_ids:
            report["rejected"].append({"why": f"new company {nc['id']}: unknown layer {nc.get('layer')}"})
            continue
        nc.update({"aliases": [nc["name"]], "first_seen": run_id})
        companies.append(nc)
        known.add(nc["id"])
        report["new_companies"].append(nc["id"])

    by_id = {d["id"]: d for d in deals}
    next_n = max([int(d["id"][1:]) for d in deals] + [0]) + 1
    for x in result.get("deals", []):
        i = x.get("item")
        if not isinstance(i, int) or not 0 <= i < len(batch):
            report["rejected"].append({"why": f"item {i} out of range", "deal": x})
            continue
        it = batch[i]
        x["from"], x["to"] = x["from"].upper(), x["to"].upper()
        if x["from"] not in known or x["to"] not in known or x["from"] == x["to"]:
            report["rejected"].append({"why": f"unknown or same party {x['from']}->{x['to']}", "title": it["title"]})
            continue
        # The one hard check against invention: the quote must be in the item.
        if not x.get("quote") or norm(x["quote"]) not in norm(it["title"] + " " + it["summary"]):
            report["rejected"].append({"why": "quote not found in item", "quote": x.get("quote"), "title": it["title"]})
            continue
        src = {"url": it["url"], "title": it["title"], "source": it["source"], "published": it["published"],
               "quote": x["quote"], "origin": "news", "run": run_id}
        old = by_id.get(x.get("same_as") or "")
        if old:
            if any(s.get("url") == src["url"] for s in old["sources"]):
                continue
            old["sources"].append(src)
            changed = False
            if not old.get("verified"):
                old["verified"] = True
                changed = True
            if x.get("usd") and x["usd"] != old.get("usd") and it["published"] >= str(old.get("date", "")):
                old.setdefault("history", []).append({"usd": old.get("usd"), "usd_text": old.get("usd_text"), "until": run_id})
                old["usd"], old["usd_text"] = x["usd"], x["usd_text"]
                changed = True
            if x.get("status") and x["status"] != old.get("status"):
                old["status"] = x["status"]
                changed = True
            if changed:
                old["updated_in"] = run_id
                if old["id"] not in report["updated_deals"]:
                    report["updated_deals"].append(old["id"])
            continue
        d = {"id": f"d{next_n:03d}", "from": x["from"], "to": x["to"], "type": x["type"],
             "usd": x.get("usd"), "usd_text": x.get("usd_text", ""), "date": x.get("date", it["published"]),
             "status": x.get("status", "announced"), "summary": x["summary"], "origin": "news",
             "verified": True, "first_seen": run_id, "sources": [src]}
        next_n += 1
        deals.append(d)
        by_id[d["id"]] = d
        report["new_deals"].append(d["id"])


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", help="YYYY-MM-DD; default: the last run's end")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-claude", action="store_true")
    ap.add_argument("--limit", type=int, help="send at most N items to Claude (testing)")
    ap.add_argument("--strict", action="store_true",
                    help="headline must name a $ billions or GW figure and a deal word: for long backfills")
    a = ap.parse_args()
    log = lambda m: print(m, flush=True)

    cfg = load(os.path.join(ROOT, "config.json"))
    cdoc = load(os.path.join(DATA, "companies.json"))
    ddoc = load(os.path.join(DATA, "deals.json"))
    seen = load(os.path.join(DATA, "seen.json"), {})
    companies, layers, deals = cdoc["companies"], cdoc["layers"], ddoc["deals"]
    os.makedirs(RUNS, exist_ok=True)
    past = sorted(f[:-5] for f in os.listdir(RUNS) if f.endswith(".json"))

    today = dt.date.today()
    if a.since:
        since = dt.date.fromisoformat(a.since)
    elif past:
        since = dt.date.fromisoformat(load(os.path.join(RUNS, past[-1] + ".json"))["until"])
    else:
        since = today - dt.timedelta(days=cfg.get("first_run_days", 7))
    run_id = dt.datetime.now().strftime("%Y-%m-%d-%H%M")
    log(f"Run {run_id}: news from {since} to {today}")

    key = env_key("FINNHUB_API_KEY")
    items = []
    if key:
        items += fetch_finnhub(companies, since, today, key, log)
    else:
        log("  FINNHUB_API_KEY not set: company news skipped")
    items += fetch_google_news(cfg.get("news_searches", []), since, log)

    fetched = len(items)
    uniq = {}
    for it in items:
        k = item_key(it["title"], it["url"])
        if k in seen or k in uniq:
            continue
        text = it["title"] + " " + it["summary"]
        if a.strict:
            ok = BIG.search(it["title"]) and DEAL.search(it["title"])
        else:
            ok = MONEY.search(text) and DEAL.search(text)
        if ok and not NOISE.search(it["title"]):
            uniq[k] = it
    cands = sorted(uniq.items(), key=lambda kv: kv[1]["published"])
    if a.limit:
        cands = cands[-a.limit:]
    log(f"Fetched {fetched}, {len(cands)} new candidates after dedupe and filter")

    report = {"id": run_id, "at": dt.datetime.now().isoformat(timespec="seconds"), "since": since.isoformat(),
              "until": today.isoformat(), "fetched": fetched, "candidates": len(cands),
              "new_deals": [], "updated_deals": [], "new_companies": [], "rejected": [], "errors": []}

    if a.no_claude:
        for _, it in cands:
            log(f"  {it['published']} {it['title']}")
        return

    size = cfg.get("batch_size", 80)
    processed = []
    for b in range(0, len(cands), size):
        chunk = cands[b:b + size]
        batch = [it for _, it in chunk]
        log(f"Claude batch {b // size + 1}/{(len(cands) + size - 1) // size}: {len(batch)} items")
        try:
            result = call_claude(build_prompt(batch, companies, layers, deals), cfg.get("model", "sonnet"))
        except Exception as e:
            # Leave these items unseen so the next run retries them.
            report["errors"].append(str(e))
            log(f"  failed: {e}")
            continue
        merge(result, batch, companies, layers, deals, run_id, report)
        processed += [k for k, _ in chunk]
        log(f"  so far: {len(report['new_deals'])} new, {len(report['updated_deals'])} updated, {len(report['rejected'])} rejected")

    by_id = {d["id"]: d for d in deals}
    name = {c["id"]: c["name"] for c in companies}
    log("")
    log(f"New deals ({len(report['new_deals'])}):")
    for i in report["new_deals"]:
        d = by_id[i]
        log(f"  + {name[d['from']]} -> {name[d['to']]}  {d['type']}  {d['usd_text']}  {d['status']}  ({d['date']}): {d['summary']}")
    log(f"Updated ({len(report['updated_deals'])}):")
    for i in report["updated_deals"]:
        d = by_id[i]
        log(f"  ~ {name[d['from']]} -> {name[d['to']]}  {d['usd_text']}  now {len(d['sources'])} source(s)")
    if report["new_companies"]:
        log(f"New companies: {', '.join(report['new_companies'])}")
    if report["rejected"]:
        log(f"Rejected {len(report['rejected'])} (listed in runs/{run_id}.json)")

    if a.dry_run:
        log("Dry run: nothing written")
        return
    if report["errors"]:
        # Keep the window open: the next run refetches it, and seen.json skips
        # the batches that did succeed.
        log(f"{len(report['errors'])} batch(es) failed; their items will be retried next run")
        report["until"] = since.isoformat()
    cutoff = (today - dt.timedelta(days=SEEN_KEEP_DAYS)).isoformat()
    seen = {k: v for k, v in seen.items() if v >= cutoff}
    for k in processed:
        seen[k] = today.isoformat()
    save(os.path.join(DATA, "seen.json"), seen)
    save(os.path.join(DATA, "companies.json"), cdoc)
    save(os.path.join(DATA, "deals.json"), ddoc)
    save(os.path.join(RUNS, run_id + ".json"), report)

    import build
    path = build.build()
    log(f"\nMap: {path}")


if __name__ == "__main__":
    sys.exit(main())
