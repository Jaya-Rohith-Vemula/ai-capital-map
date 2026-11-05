"""Claude reads the news items (with article text where we could read it) and
returns deals; the code checks them and merges them into the ledger.
"""

import json
import os
import re
import subprocess

import news

ROOT = os.path.dirname(os.path.abspath(__file__))
TYPES = ["equity", "compute", "chips", "lease", "power", "financing", "acquisition", "partnership"]
STATUSES = ["announced", "loi", "reported", "completed", "terminated"]
# Best first: how directly the deal's source states it.
EVIDENCE = ["press release", "article", "summary", "headline"]

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
                "usd": {"type": ["number", "null"], "description": "headline US dollar value; null if none stated or not in USD"},
                "usd_text": {"type": "string", "description": "short label as stated: '$9.7B', 'up to $100B', '1.2 GW', 'NT$16B'"},
                "date": {"type": "string", "description": "YYYY-MM-DD or YYYY-MM the deal was announced"},
                "status": {"type": "string", "enum": STATUSES,
                           "description": "announced = signed/definitive; loi = letter of intent, memorandum or non-binding; "
                                          "reported = media report the companies have not confirmed; completed = closed; terminated = cancelled"},
                "summary": {"type": "string", "description": "one or two sentences: what, how much, over how long, conditions"},
                "quote": {"type": "string", "description": "verbatim span from the item's title, summary or article text that states the deal"},
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

A deal is money or a binding commitment between two named organisations in the AI supply chain: equity investments, compute or cloud contracts, chip, memory or server purchases, data-center leases, power purchase agreements, financing or lease backstops, acquisitions, and named partnerships. "from" pays, invests or buys; "to" receives or supplies.

Each item has a TITLE, sometimes a SUMMARY, and sometimes ARTICLE text read from the publisher. Read the article when there is one: it carries the amount, term, conditions and whether the deal is binding, which a headline often drops.

Rules:
- Use only what the item says. Never add amounts, dates or parties from your own knowledge.
- quote must be copied character for character from that item's TITLE, SUMMARY or ARTICLE. Prefer the sentence that carries the amount.
- status: announced only for signed or definitive agreements the companies confirmed. A letter of intent, memorandum of understanding, framework or "up to" commitment tied to milestones is loi. A media report citing unnamed sources is reported.
- usd is in US dollars only. A figure in another currency goes in usd_text with usd null.
- Skip analyst opinions, price targets, rumours of talks with no agreement, earnings results, product launches, and capex plans with no counterparty.
- Use existing company ids. If a party is not in the list but clearly belongs in the AI build-out, add it to new_companies (layer must be one of the given layer ids) and use its id. Otherwise skip the deal.
- If the ledger already holds the same deal (same parties, same agreement), set same_as to its id, even when the amount was revised. An expansion announced as a separate new agreement is a new deal.
- One item can give several deals, or none. Most give none. Return each deal once even if several items report it."""


def build_prompt(batch, companies, layers, deals):
    comp = "\n".join(f"{c['id']}: {c['name']} ({', '.join(c.get('aliases', []))})" for c in companies)
    ledger = "\n".join(f"{d['id']}: {d['from']}->{d['to']} {d['type']} {d.get('usd_text', '')} {d.get('date', '')}: {d['summary']}"
                       for d in deals)
    parts = []
    for i, it in enumerate(batch):
        s = f"[{i}] {it['published']} {it['source']}\nTITLE: {it['title']}"
        if it["summary"]:
            s += f"\nSUMMARY: {it['summary'][:800]}"
        if it["text"]:
            s += f"\nARTICLE:\n{news.relevant(it['text'])}"
        parts.append(s)
    return (f"LAYERS: {', '.join(l['id'] for l in layers)}\n\nCOMPANIES:\n{comp}\n\nLEDGER:\n{ledger}\n\n"
            f"NEWS ITEMS:\n" + "\n\n".join(parts) + "\n\nReturn the deals these items state.")


def call_claude(prompt, model):
    cmd = ["claude", "-p", "--model", model, "--tools", "", "--no-session-persistence",
           "--output-format", "json", "--system-prompt", SYSTEM, "--json-schema", json.dumps(SCHEMA)]
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=1200, cwd=ROOT)
    if r.returncode != 0:
        raise RuntimeError(f"claude exited {r.returncode}: {(r.stderr or r.stdout).strip()[:400]}")
    out = json.loads(r.stdout)
    if out.get("is_error") or "structured_output" not in out:
        raise RuntimeError(f"claude: {out.get('subtype')} {str(out.get('result'))[:300]}")
    return out["structured_output"]


def evidence_of(it, quote):
    q = news.norm(quote)
    if it["text"] and q in news.norm(it["text"]):
        wire = news.PRESS_WIRES.search(it["source"] or "") or news.PRESS_WIRES.search(it["url"] or "")
        return "press release" if wire else "article"
    if it["summary"] and q in news.norm(it["summary"]):
        return "summary"
    if q in news.norm(it["title"]):
        return "headline"
    return None


def best(a, b):
    return min([a, b], key=lambda e: EVIDENCE.index(e) if e in EVIDENCE else 99)


def merge(result, batch, companies, layers, deals, run_id, report):
    known = {c["id"] for c in companies}
    layer_ids = {l["id"] for l in layers}
    for nc in result.get("new_companies", []):
        nc["id"] = re.sub(r"[^A-Z0-9.]", "", nc["id"].upper())
        if not nc["id"] or nc["id"] in known:
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
            report["rejected"].append({"why": f"item {i} out of range"})
            continue
        it = batch[i]
        x["from"], x["to"] = x["from"].upper(), x["to"].upper()
        if x["from"] not in known or x["to"] not in known or x["from"] == x["to"]:
            report["rejected"].append({"why": f"unknown or same party {x['from']}->{x['to']}", "title": it["title"]})
            continue
        # The one hard check against invention: the quote must be in the item.
        ev = evidence_of(it, x.get("quote") or "") if x.get("quote") else None
        if not ev:
            report["rejected"].append({"why": "quote not found in item", "quote": x.get("quote"), "title": it["title"]})
            continue
        src = {"url": it["url"] or it["link"], "title": it["title"], "source": it["source"], "published": it["published"],
               "quote": x["quote"], "evidence": ev, "run": run_id}
        old = by_id.get(x.get("same_as") or "")
        if old:
            if any(s.get("title") == src["title"] for s in old["sources"]):
                continue
            old["sources"].append(src)
            changed = False
            prev = old.get("evidence", "headline")
            old["evidence"] = best(prev, ev)
            if old["evidence"] != prev or not old.get("verified"):
                old["verified"] = True
                changed = True
            # A better-evidenced source, or a newer one, may correct the terms.
            if (EVIDENCE.index(ev) < EVIDENCE.index(prev) or it["published"] >= str(old.get("date", ""))) and \
                    (x.get("usd") != old.get("usd") or x.get("status") != old.get("status")):
                old.setdefault("history", []).append(
                    {"usd": old.get("usd"), "usd_text": old.get("usd_text"), "status": old.get("status"), "until": run_id})
                old["usd"], old["usd_text"], old["status"] = x.get("usd"), x["usd_text"], x["status"]
                old["summary"] = x["summary"]  # the old sentence names the old terms
                changed = True
            if changed:
                old["updated_in"] = run_id
                if old["id"] not in report["updated_deals"] and old["id"] not in report["new_deals"]:
                    report["updated_deals"].append(old["id"])
            continue
        d = {"id": f"d{next_n:03d}", "from": x["from"], "to": x["to"], "type": x["type"],
             "usd": x.get("usd"), "usd_text": x.get("usd_text", ""), "date": x.get("date") or it["published"],
             "status": x.get("status", "announced"), "summary": x["summary"], "origin": "news", "evidence": ev,
             "verified": True, "first_seen": run_id, "sources": [src]}
        next_n += 1
        deals.append(d)
        by_id[d["id"]] = d
        report["new_deals"].append(d["id"])
