#!/usr/bin/env python3
"""Write the public data for the website: web/public/data.json.

    python3 export.py             # export (rewrites only summaries that changed)
    python3 export.py --no-claude # export with what is cached; fail if a rewrite is missing

What the public site shows, and what it leaves out:

- No money amounts. Deal amounts come from news reports read by Claude, not
  from official filings, so the site shows who dealt with whom, the kind of
  deal, its status and date, and links to the sources, never "$X". The
  ledger keeps the amounts; they are just not exported.
- Summaries are rewritten by Claude without amounts, once per summary, and
  cached in data/public_text.json (a summary that changes is rewritten again).
  Every rewritten text is checked for money before it is used.
- No unverified seed deals (Claude's training knowledge with no news item).
- Sources as publisher, date and link only: no headlines (they carry the
  amounts) and no quotes (the publishers' text).
- Companies only if they have at least one public deal.
- SEC financials are official filings and are included.
"""

import datetime as dt
import hashlib
import json
import os
import re
import sys


ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "web", "public", "data.json")
CACHE = os.path.join(ROOT, "data", "public_text.json")
BATCH = 60

MONEY = re.compile(
    r"(\$|€|£|¥|₩|\b(?:USD|EUR|GBP|JPY|KRW|TWD|NT\$|A\$|C\$|RM|INR|CNY|yuan)\b(?!\.AI)"
    r"|\b\d[\d.,]*\s*(?:billion|million|trillion|bn|mn|tn)\b(?!\s+(?:[A-Z][\w.]*\s+|Nvidia RTX Pro \d+\s+)?(?:shares|GPUs|chips|TPUs|units|miles))"
    r"|\b\d[\d.,]*\s?[BT]\b(?!W))", re.I)

SYSTEM = """You rewrite one-sentence summaries of business deals for a public website that must not state any money amounts.
Remove every monetary figure: dollar or other currency amounts, valuations, prices, "worth", "multi-billion", "$X per share", percentages of a price. Keep who did what with whom, what the deal is (product, service, capacity, stake), timing and conditions. Capacity in MW or GW, chip counts, years and durations may stay.
Drop bookkeeping notes such as "already in ledger" or "same as". Do not add facts. Keep it to one plain sentence, under 30 words. If nothing remains without the amount, describe the kind of deal between the two parties."""

SCHEMA = {"type": "object", "properties": {"items": {"type": "array", "items": {
    "type": "object", "properties": {"key": {"type": "string"}, "text": {"type": "string"}},
    "required": ["key", "text"]}}}, "required": ["items"]}


def load(*p):
    with open(os.path.join(ROOT, *p)) as f:
        return json.load(f)


def save(path, obj, indent=1):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=indent, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def h(s):
    return hashlib.sha1(s.encode()).hexdigest()[:12]


def rewrite(todo, model):
    """todo: {key: original}. Returns {key: rewritten}, money-free only."""
    import subprocess
    out = {}
    keys = list(todo)
    for i in range(0, len(keys), BATCH):
        chunk = keys[i:i + BATCH]
        prompt = "Rewrite each summary. Return every key.\n\n" + "\n".join(f"{k}: {todo[k]}" for k in chunk)
        cmd = ["claude", "-p", "--model", model, "--tools", "", "--no-session-persistence",
               "--output-format", "json", "--system-prompt", SYSTEM, "--json-schema", json.dumps(SCHEMA)]
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=1200, cwd=ROOT)
        if r.returncode != 0:
            raise RuntimeError(f"claude exited {r.returncode}: {(r.stderr or r.stdout).strip()[:300]}")
        res = json.loads(r.stdout)
        if res.get("is_error") or "structured_output" not in res:
            raise RuntimeError(f"claude: {res.get('subtype')} {str(res.get('result'))[:300]}")
        for it in res["structured_output"]["items"]:
            if it["key"] not in todo:
                continue
            m = MONEY.search(it["text"])
            if m:
                print(f"  {it['key']}: rewrite still has money ({m.group(0)!r}), skipped: {it['text']}")
            else:
                out[it["key"]] = it["text"].strip()
        print(f"  rewrote {min(i + BATCH, len(keys))}/{len(keys)}")
    return out


def main(argv):
    cfg = load("config.json")
    cdoc, ddoc = load("data", "companies.json"), load("data", "deals.json")
    fund = load("data", "fundamentals.json").get("companies", {}) if os.path.exists(
        os.path.join(ROOT, "data", "fundamentals.json")) else {}
    cache = load("data", "public_text.json") if os.path.exists(CACHE) else {}

    deals = [d for d in ddoc["deals"] if d.get("verified") and d.get("from") != d.get("to")]
    used = {d["from"] for d in deals} | {d["to"] for d in deals}
    comps = [c for c in cdoc["companies"] if c["id"] in used]

    # Text to make public: deal summaries always, company descriptions only if they mention money.
    texts = {f"D:{d['id']}": d.get("summary") or "" for d in deals}
    texts.update({f"C:{c['id']}": c.get("does") or "" for c in comps if MONEY.search(c.get("does") or "")})
    todo = {k: v for k, v in texts.items() if v and (cache.get(k, {}).get("src") != h(v))}
    if todo:
        if "--no-claude" in argv:
            sys.exit(f"export: {len(todo)} summaries need rewriting; run without --no-claude")
        print(f"export: rewriting {len(todo)} summaries without amounts ({cfg.get('model', 'sonnet')})")
        done = rewrite(todo, cfg.get("model", "sonnet"))
        for k, t in done.items():
            cache[k] = {"src": h(texts[k]), "text": t}
        save(CACHE, dict(sorted(cache.items())))
        missing = set(todo) - set(done)
        if missing:
            print(f"  {len(missing)} not rewritten (will retry next export): {', '.join(sorted(missing)[:10])}")

    def public(k, original):
        c = cache.get(k)
        if c and c["src"] == h(original):
            return c["text"]
        return None if MONEY.search(original) else original

    out_comps = []
    for c in comps:
        f = fund.get(c["id"])
        does = public(f"C:{c['id']}", c.get("does") or "") if MONEY.search(c.get("does") or "") else c.get("does")
        row = {"id": c["id"], "name": c["name"], "ticker": c.get("ticker"), "layer": c["layer"], "does": does or ""}
        if "market" in c:
            row["market"] = c["market"]
        if f:
            row["fin"] = {k: f[k] for k in ("currency", "annual", "quarterly", "last_filed", "cik", "exchange")}
        out_comps.append(row)

    out_deals = []
    for d in deals:
        out_deals.append({
            "id": d["id"], "from": d["from"], "to": d["to"], "type": d["type"],
            "status": d.get("status"), "date": d.get("date"), "evidence": d.get("evidence"),
            "summary": public(f"D:{d['id']}", d.get("summary") or "") or "",
            "first_seen": d.get("first_seen"),
            "sources": [{"source": s.get("source"), "published": s.get("published"), "url": s.get("url")}
                        for s in d.get("sources", []) if s.get("url")],
        })

    blob = json.dumps(out_deals + out_comps, ensure_ascii=False)
    leaks = [x["id"] for x in out_deals + out_comps if MONEY.search((x.get("summary") or "") + (x.get("does") or ""))]
    assert not leaks, f"money left in: {leaks}"
    assert '"usd' not in blob

    runs = sorted(n for n in os.listdir(os.path.join(ROOT, "runs")) if n.endswith(".json"))
    covered = max((load("runs", n).get("until") or "" for n in runs), default=None)
    data = {
        "built_at": dt.datetime.now().strftime("%Y-%m-%d"),
        "covered_until": covered, "start": cfg.get("start"),
        "fundamentals_as_of": load("data", "fundamentals.json").get("as_of") if fund else None,
        "layers": cdoc["layers"], "companies": out_comps, "deals": out_deals,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    save(OUT, data, indent=None)
    print(f"export: {len(out_deals)} deals, {len(out_comps)} companies → {os.path.relpath(OUT, ROOT)} "
          f"({os.path.getsize(OUT) // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
