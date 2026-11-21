#!/usr/bin/env python3
"""Fundamentals from SEC filings: revenue, net income, diluted EPS, capex,
operating cash flow, for every listed company that files with the SEC.

    python3 fundamentals.py            # refresh data/fundamentals.json
    python3 fundamentals.py NVDA TSM   # just these tickers (others kept)
    python3 fundamentals.py --if-older 7   # only if the file is over 7 days old

Source: data.sec.gov companyfacts (XBRL as filed in 10-K, 10-Q, 20-F, 40-F).
Free, no key; SEC asks for at most 10 requests a second and a User-Agent
that says who is asking: set SEC_USER_AGENT in .env (e.g. "Your Name you@x.com").

US government data, so it can be shown on a public site. Prices, P/E and
market cap are not here: the map shows those through the TradingView widget.

Each company's SEC name is checked against ours before its filings are used,
because tickers get reused (NXT is NEXTDC on the ASX but Nextpower on Nasdaq).
"""

import datetime as dt
import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "data", "fundamentals.json")
TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{:010d}.json"
FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "40-F/A", "10-KT"}

# Per metric, the XBRL concepts that carry it, best first. Companies switch
# concepts over the years; see pick() for how they are combined.
CONCEPTS = {
    "revenue": [("us-gaap", "Revenues"), ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
                ("us-gaap", "RevenueFromContractWithCustomerIncludingAssessedTax"), ("us-gaap", "SalesRevenueNet"),
                ("ifrs-full", "Revenue")],
    "net_income": [("us-gaap", "NetIncomeLoss"), ("us-gaap", "ProfitLoss"),
                   ("ifrs-full", "ProfitLossAttributableToOwnersOfParent"), ("ifrs-full", "ProfitLoss")],
    "eps": [("us-gaap", "EarningsPerShareDiluted"), ("us-gaap", "EarningsPerShareBasicAndDiluted"),
            ("ifrs-full", "DilutedEarningsLossPerShare")],
    "capex": [("us-gaap", "PaymentsToAcquirePropertyPlantAndEquipment"), ("us-gaap", "PaymentsToAcquireProductiveAssets"),
              ("us-gaap", "PaymentsForCapitalImprovements"),
              ("ifrs-full", "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities")],
    "ocf": [("us-gaap", "NetCashProvidedByUsedInOperatingActivities"),
            ("us-gaap", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"),
            ("ifrs-full", "CashFlowsFromUsedInOperatingActivities")],
}
FLOW = {"revenue", "net_income", "capex", "ocf"}   # summable over time; EPS is not
KEEP_YEARS, KEEP_QUARTERS = 5, 12

GENERIC = {"inc", "corp", "corporation", "co", "company", "group", "holdings", "holding", "ltd", "limited",
           "plc", "nv", "sa", "se", "ag", "the", "and", "of", "de", "tx", "ny", "uk", "llc", "lp", "trust", "technologies"}


def user_agent():
    if os.environ.get("SEC_USER_AGENT"):
        return os.environ["SEC_USER_AGENT"]
    try:
        with open(os.path.join(ROOT, ".env")) as f:
            for line in f:
                k, _, v = line.strip().partition("=")
                if k == "SEC_USER_AGENT":
                    return v.strip().strip('"')
    except FileNotFoundError:
        pass
    sys.exit('fundamentals: set SEC_USER_AGENT in .env, e.g. SEC_USER_AGENT="Your Name you@example.com"\n'
             '  (SEC refuses requests without a contact address)')


def get(url, tries=3):
    req = urllib.request.Request(url, headers={"User-Agent": user_agent(), "Accept-Encoding": "gzip"})
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                return json.loads(body)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if i == tries - 1:
                raise
        except (urllib.error.URLError, TimeoutError):
            if i == tries - 1:
                raise
        time.sleep(2 * (i + 1))


def words(s):
    return [w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in GENERIC]


def same_company(ours, sec_name):
    """Does SEC's name for the ticker plausibly mean our company?"""
    theirs = words(sec_name)
    flat = "".join(theirs)
    # Initials keep "group", "co" etc.: MUFG is Mitsubishi UFJ Financial Group.
    initials = "".join(w[0] for w in re.findall(r"[a-z0-9]+", sec_name.lower())
                       if w not in {"inc", "corp", "ltd", "plc", "nv", "sa", "se", "llc", "de", "tx", "ny", "uk"})
    for name in ours:
        mine = words(name)
        if set(mine) & set(theirs):
            return True
        m = "".join(mine)
        if m and (m in flat or initials.startswith(m)):
            return True
        if any(len(w) >= 3 and initials.startswith(w) for w in mine):   # "MUFG Bank"
            return True
    return False


def days(a, b):
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


def periods(facts, tax, name):
    """{(start, end): val} for one concept, in its main unit, latest filing wins."""
    node = facts.get(tax, {}).get(name)
    if not node:
        return None, {}
    # The unit with the most facts is the reporting currency (20-F filers add
    # USD convenience translations for the latest year only).
    unit = max(node["units"], key=lambda u: len(node["units"][u]))
    out, filed, in_annual = {}, {}, set()
    for f in node["units"][unit]:
        if f.get("form") not in FORMS or "start" not in f:
            continue
        k = (f["start"], f["end"])
        if f["form"][:4] not in ("10-Q",):
            in_annual.add(k)
        if k not in filed or f["filed"] >= filed[k]:
            out[k], filed[k] = f["val"], f["filed"]
    # A 12-month figure only a 10-Q carries is a trailing twelve months
    # (Amazon reports these), not a fiscal year: drop it.
    out = {k: v for k, v in out.items() if k in in_annual or not 350 <= days(*k) + 1 <= 380}
    return unit, out


def split(p, flow):
    """Annual and single-quarter values by period end, from as-filed periods.
    10-Qs report cash flows year-to-date, and nobody files a Q4, so for flows
    a quarter is also derived as the difference of two year-to-date figures."""
    annual, quarter = {}, {}
    for (s, e), v in p.items():
        n = days(s, e) + 1
        if 350 <= n <= 380:
            annual[e] = v
        elif 80 <= n <= 100:
            quarter[e] = v
    if flow:
        by_start = {}
        for (s, e), v in p.items():
            by_start.setdefault(s, []).append((e, v))
        for s, rows in by_start.items():
            rows.sort()
            for (e0, v0), (e1, v1) in zip(rows, rows[1:]):
                if 80 <= days(e0, e1) <= 100 and e1 not in quarter:
                    quarter[e1] = v1 - v0
    return annual, quarter


def pick(facts, metric):
    """Combine a metric's concepts: the one with the most recent data leads,
    older periods it lacks are filled from the others."""
    found = []
    for tax, name in CONCEPTS[metric]:
        unit, p = periods(facts, tax, name)
        if p:
            a, q = split(p, metric in FLOW)
            last = max(list(a) + list(q) or [""])
            found.append((last, unit, a, q))
    if not found:
        return None, {}, {}
    found.sort(key=lambda x: x[0], reverse=True)
    unit, annual, quarter = found[0][1], dict(found[0][2]), dict(found[0][3])
    for _, u, a, q in found[1:]:
        if u != unit:
            continue
        for e, v in a.items():
            annual.setdefault(e, v)
        for e, v in q.items():
            quarter.setdefault(e, v)
    return unit, annual, quarter


def rows(series, keep):
    ends = sorted({e for s in series.values() for e in s}, reverse=True)
    # Two concepts can end the same period a day or two apart; keep one row.
    merged = []
    for e in ends:
        if merged and days(e, merged[-1]["end"]) <= 7:
            row = merged[-1]
        else:
            row = {"end": e}
            merged.append(row)
        for m, s in series.items():
            if e in s and m not in row:
                row[m] = s[e]
    return merged[:keep]


def company(cik, facts_doc):
    facts = facts_doc.get("facts", {})
    out, units_seen = {}, {}
    annual, quarter = {}, {}
    for m in CONCEPTS:
        unit, a, q = pick(facts, m)
        if unit:
            units_seen[m] = unit
            annual[m], quarter[m] = a, q
    if not annual:
        return None
    money = [u for m, u in units_seen.items() if m != "eps"]
    currency = max(set(money), key=money.count) if money else None
    out["currency"] = currency
    out["annual"] = rows(annual, KEEP_YEARS)
    out["quarterly"] = rows(quarter, KEEP_QUARTERS)
    filed = [f["filed"] for tax in facts.values() for c in tax.values() for u in c["units"].values()
             for f in u if f.get("form") in FORMS]
    out["last_filed"] = max(filed) if filed else None
    return out


def main(argv):
    only = {a.upper() for a in argv if not a.startswith("--")}
    if "--if-older" in argv:
        limit = float(argv[argv.index("--if-older") + 1])
        only = {a for a in only if a != argv[argv.index("--if-older") + 1]}
        if os.path.exists(OUT) and time.time() - os.path.getmtime(OUT) < limit * 86400:
            print(f"fundamentals: fresh (under {limit:g} days old), skipped")
            return 0

    with open(os.path.join(ROOT, "data", "companies.json")) as f:
        comps = json.load(f)["companies"]
    old = {}
    if os.path.exists(OUT):
        with open(OUT) as f:
            old = json.load(f).get("companies", {})

    sec = get(TICKERS_URL)
    by_ticker = {r[2]: dict(zip(sec["fields"], r)) for r in sec["data"]}
    result, skipped = {}, []
    for c in comps:
        t = c.get("ticker")
        if not t:
            continue
        if only and t.upper() not in only:
            if c["id"] in old:
                result[c["id"]] = old[c["id"]]
            continue
        row = by_ticker.get(t)
        if not row:
            skipped.append(f"{t} (not an SEC filer)")
            continue
        if not same_company([c["name"]] + c.get("aliases", []), row["name"]):
            skipped.append(f"{t} (SEC has it as {row['name']})")
            continue
        time.sleep(0.15)
        doc = get(FACTS_URL.format(row["cik"]))
        data = company(row["cik"], doc) if doc else None
        if not data:
            skipped.append(f"{t} (no XBRL financials)")
            continue
        result[c["id"]] = {"ticker": t, "cik": row["cik"], "sec_name": row["name"], "exchange": row["exchange"], **data}
        a = data["annual"][0] if data["annual"] else {}
        print(f"  {t:6} {row['name'][:32]:32} {data['currency'] or '':4} last filed {data['last_filed']}"
              f"  FY to {a.get('end', '-')}: {len(data['annual'])}y {len(data['quarterly'])}q")

    doc = {"source": "SEC EDGAR XBRL companyfacts (data.sec.gov), as filed",
           "as_of": dt.date.today().isoformat(), "companies": result}
    tmp = OUT + ".tmp"
    with open(tmp, "w") as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, OUT)
    print(f"fundamentals: {len(result)} companies → {os.path.relpath(OUT, ROOT)}")
    if skipped:
        print("  not from SEC: " + "; ".join(skipped))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
