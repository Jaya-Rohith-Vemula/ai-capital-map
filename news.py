"""Finding and reading the news: Google News search, Finnhub (short runs only),
resolving Google's redirect links, fetching articles and keeping the text.
"""

import datetime as dt
import email.utils
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import store

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
PAUSE = 1.0           # between requests to the same service
REFUSALS_TO_SKIP = 3  # a domain that refused this many times is not asked again

# Outlets that refuse scripts or sit behind a paywall (measured 2026-11-05).
# Their headlines still count; we just do not ask for the article.
BLOCKED_SOURCES = re.compile(r"bloomberg|reuters|wall street journal|\bwsj\b|financial times|\bft\.com|barron|forbes|"
                             r"the information|business ?wire|inc\.com|\bnikkei|economist", re.I)
PRESS_WIRES = re.compile(r"prnewswire|globenewswire|businesswire|accesswire|newsfilecorp", re.I)

MONEY = re.compile(r"\$\s?\d|\bbillion\b|\bbn\b|\bmillion\b|\bGW\b|gigawatt|megawatt|\bMW\b|\bstake\b|\bwarrants?\b", re.I)
DEAL = re.compile(r"invest|stake|\bdeal\b|contract|agreement|partner|supply|\border|acquir|purchas|\bbuy|lease|backstop|"
                  r"financ|\bloan|warrant|offtake|\bPPA\b|power purchase|commit|capacity|\bsigns?\b|\binks?\b|\bfund", re.I)
# Commentary, not news of a deal. The same deal is nearly always also
# reported under a plain headline, so dropping these loses little.
NOISE = re.compile(r"price target|\bmaintains\b|reiterat|\bupgrades?\b|\bdowngrades?\b|if you(?: had)? invested|"
                   r"should you buy|\bbuy\?|fairly valued|\bvaluation check|undervalued|overvalued|no-brainer|millionaire|"
                   r"stocks? to (?:buy|watch|own)|what to watch|\bvs\.? |\bvs\b|motley|\bdividend\b|"
                   r"(?:shares|stock) (?:rise|rises|fall|falls|jump|jumps|soar|soars|drop|drops|slide|slides|surge|surges)|"
                   r"\bETFs?\b|\bSPDR\b|\biShares\b|would be worth|worth (?:by|today|this much)|per month|net buying|"
                   r"\bearnings (?:call|preview)|\bQ[1-4] (?:earnings|results)|options activity|unusual options|"
                   r"\b(?:sells|buys) \$[\d.,]+ (?:million|billion)|\$[\d,]+ investment in|\$[\d,]+ invested|fair value", re.I)


class RateLimited(Exception):
    """Google kept saying slow down through every retry. The run stops cleanly
    and the window stays open."""


# On 429/503 from Google: wait and retry, doubling (15 s ... 8 min, ~16 min
# in all), before giving up the run. A Retry-After header wins when given.
BACKOFF = [15, 30, 60, 120, 240, 480]
on_wait = lambda msg: None  # run.py points this at its log


def google_http(what, url, data=None, headers=None):
    for n, wait in enumerate(BACKOFF + [None], 1):
        try:
            return http(url, data, headers)
        except urllib.error.HTTPError as e:
            if e.code not in (429, 503):
                raise
            if wait is None:
                raise RateLimited(f"{what} answered {e.code} through {len(BACKOFF)} retries")
            try:
                wait = max(wait, min(900, int(e.headers.get("Retry-After") or 0)))
            except ValueError:
                pass
            on_wait(f"  {what} answered {e.code}; retry {n}/{len(BACKOFF)} in {wait} s")
            time.sleep(wait)


def http(url, data=None, headers=None, timeout=25):
    h = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.geturl(), r.read().decode("utf-8", "replace")


def norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def key_for(title):
    # Google appends " - Publisher"; the same story from two outlets should
    # still be two items (two chances to read it), so keep the suffix.
    return hashlib.sha1(norm(title).encode()).hexdigest()[:16]


def is_candidate(title, summary, loose=False):
    """A deal headline: money and a deal word, not commentary. loose (topic
    searches) drops the money test: an acquisition or funding headline often
    names no amount."""
    text = title + " " + summary
    return bool((loose or MONEY.search(text)) and DEAL.search(text) and not NOISE.search(title))


# ---------- finding ----------

def google_search(query, since, until, log):
    """One Google News search over [since, until]."""
    if (dt.date.today() - since).days <= 21 and until >= dt.date.today() - dt.timedelta(days=1):
        window = f"when:{max(1, (dt.date.today() - since).days)}d"
    else:
        window = f"after:{since.isoformat()} before:{(until + dt.timedelta(days=1)).isoformat()}"
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": f"{query} {window}", "hl": "en-US", "gl": "US", "ceid": "US:en"})
    try:
        _, body = google_http("Google News search", url)
    except urllib.error.HTTPError as e:
        log(f"  search failed ({e.code}): {query}")
        return []
    except Exception as e:
        log(f"  search failed ({e}): {query}")
        return []
    out = []
    for it in ET.fromstring(body).iter("item"):
        try:
            day = email.utils.parsedate_to_datetime(it.findtext("pubDate")).date()
        except Exception:
            continue
        if not since <= day <= until:
            continue
        title = it.findtext("title") or ""
        out.append({"key": key_for(title), "title": title, "summary": "", "source": it.findtext("source") or "",
                    "published": day.isoformat(), "feed": "google:" + query, "link": it.findtext("link") or ""})
    return out


def finnhub_news(ticker, since, until, key):
    q = urllib.parse.urlencode({"symbol": ticker, "from": since.isoformat(), "to": until.isoformat(), "token": key})
    _, body = http("https://finnhub.io/api/v1/company-news?" + q)
    rows = json.loads(body)
    time.sleep(1.1)  # free tier: 60 calls a minute
    # At most ~250 rows a call, newest first: a full page means older ones
    # were cut off, so split the window and ask again.
    if len(rows) >= 240 and since < until:
        mid = since + (until - since) // 2
        return finnhub_news(ticker, since, mid, key) + finnhub_news(ticker, mid + dt.timedelta(days=1), until, key)
    out = []
    for r in rows:
        title = r.get("headline", "")
        out.append({"key": key_for(title), "title": title, "summary": r.get("summary", ""), "source": r.get("source", ""),
                    "published": dt.datetime.fromtimestamp(r.get("datetime", 0), dt.timezone.utc).date().isoformat(),
                    "feed": "finnhub:" + ticker, "link": r.get("url", ""), "url": r.get("url", "")})
    return out


# ---------- reading ----------

def resolve_google(link):
    """Google News links are redirects behind a JS page; this asks Google's own
    endpoint for the publisher URL (two requests)."""
    gid = urllib.parse.urlparse(link).path.rstrip("/").split("/")[-1]
    try:
        _, page = google_http("Google link resolver", f"https://news.google.com/rss/articles/{gid}")
        sig = re.search(r'data-n-a-sg="([^"]+)"', page).group(1)
        ts = re.search(r'data-n-a-ts="([^"]+)"', page).group(1)
        time.sleep(PAUSE)
        inner = ["garturlreq", [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None, None, None, None, 0, 1],
                                "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0], gid, int(ts), sig]
        body = urllib.parse.urlencode({"f.req": json.dumps([[["Fbv4je", json.dumps(inner), None, "generic"]]])}).encode()
        _, out = google_http("Google link resolver", "https://news.google.com/_/DotsSplashUi/data/batchexecute", body,
                             {"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
        return json.loads(json.loads(out.split("\n\n")[1])[0][2])[1]
    except RateLimited:
        raise


def article_text(html):
    html = re.sub(r"(?is)<(script|style|noscript|nav|footer|aside|form)[^>]*>.*?</\1>", " ", html)
    paras = []
    for p in re.findall(r"(?is)<p[^>]*>(.*?)</p>", html):
        t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", p))
        t = t.replace("&amp;", "&").replace("&nbsp;", " ").replace("&#39;", "'").replace("&quot;", '"').replace("&rsquo;", "'").strip()
        if len(t) > 50 and t not in paras:
            paras.append(t)
    return "\n".join(paras)


def domain_of(url):
    d = urllib.parse.urlparse(url).netloc.lower()
    return d[4:] if d.startswith("www.") else d


def read_item(db, row, log):
    """Resolve and fetch one candidate; records the outcome in the store."""
    def done(state, note=None, url=None, text=None):
        db.execute("UPDATE items SET fetch = ?, fetch_note = ?, url = COALESCE(?, url), text = COALESCE(?, text) WHERE key = ?",
                   (state, note, url, text, row["key"]))
        db.commit()
        return state

    if BLOCKED_SOURCES.search(row["source"]) and not PRESS_WIRES.search(row["source"]):
        return done("blocked", "known paywall or bot block")
    url = row["url"]
    if not url:
        try:
            url = resolve_google(row["link"])
            time.sleep(PAUSE)
        except RateLimited:
            raise
        except Exception as e:
            return done("failed", f"resolve: {str(e)[:120]}")
    dom = domain_of(url)
    # Finnhub links are its own redirects: the domain that matters is where
    # they land, so refusals are counted against that, never finnhub.io.
    if dom != "finnhub.io" and store.refusals(db, dom) >= REFUSALS_TO_SKIP:
        return done("blocked", f"{dom} refused {REFUSALS_TO_SKIP}+ times", url)
    try:
        final, html = http(url, timeout=20)
    except urllib.error.HTTPError as e:
        land = domain_of(e.geturl() or url)
        if e.code in (401, 402, 403, 451) and land != "finnhub.io":
            store.refused(db, land)
            return done("blocked", f"HTTP {e.code} from {land}", e.geturl() or url)
        return done("failed", f"HTTP {e.code} from {land}", url)
    except Exception as e:
        return done("failed", str(e)[:120], url)
    finally:
        time.sleep(PAUSE / 2)
    url = final
    if BLOCKED_SOURCES.search(domain_of(url)):
        return done("blocked", f"landed on {domain_of(url)}", url)
    text = article_text(html)
    if len(text) < 300:
        return done("short", f"{len(text)} chars of text (paywall or script-rendered page)", url, text or None)
    return done("read", f"{len(text)} chars", url, text)


def relevant(text, limit=3500):
    """The opening paragraphs plus every paragraph naming money or a deal,
    within a budget: the part of the article a deal lives in."""
    paras = text.split("\n")
    keep = []
    for i, p in enumerate(paras):
        if i < 3 or (MONEY.search(p) and DEAL.search(p)):
            keep.append(p)
    out = "\n".join(keep)
    return out[:limit]
