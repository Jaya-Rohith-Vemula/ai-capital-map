"""The local news store: store/news.db (SQLite, standard library).

Every headline we have seen, its real URL, whether the article could be read,
and the article's text, so nothing is fetched twice and deals can be
re-extracted later without downloading again. Local only: the text is the
publishers' copyright, so store/ is gitignored and never pushed.
"""

import datetime as dt
import os
import sqlite3

ROOT = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(ROOT, "store", "news.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  key         TEXT PRIMARY KEY,   -- hash of the normalised headline: one story, many feeds
  title       TEXT NOT NULL,
  summary     TEXT NOT NULL DEFAULT '',
  source      TEXT NOT NULL DEFAULT '',
  published   TEXT NOT NULL,      -- YYYY-MM-DD
  feed        TEXT NOT NULL,      -- google:<query> or finnhub:<ticker>, first seen
  link        TEXT NOT NULL,      -- as the feed gave it (Google redirect for google:)
  url         TEXT,               -- the publisher's URL once resolved
  candidate   INTEGER NOT NULL DEFAULT 0,   -- passed the money-and-deal filter
  fetch       TEXT NOT NULL DEFAULT 'pending',
              -- pending | read | blocked (401/403/known paywall) | failed | short | skipped
  fetch_note  TEXT,
  text        TEXT,               -- article paragraphs, when read
  extracted   TEXT,               -- run id that sent it to Claude
  added_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS items_pub ON items (published);
CREATE TABLE IF NOT EXISTS domains (
  domain      TEXT PRIMARY KEY,
  refusals    INTEGER NOT NULL DEFAULT 0  -- 401/403s; past a few, stop asking
);
"""


def connect():
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    db = sqlite3.connect(PATH)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def add_item(db, it):
    """Insert a headline if new. Returns True when it was new."""
    cur = db.execute(
        "INSERT OR IGNORE INTO items (key, title, summary, source, published, feed, link, url, candidate, added_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (it["key"], it["title"], it.get("summary", ""), it.get("source", ""), it["published"], it["feed"],
         it["link"], it.get("url"), int(it.get("candidate", 0)), dt.datetime.now().isoformat(timespec="seconds")))
    if not cur.rowcount and it.get("summary"):
        # A Finnhub summary is worth keeping even if Google saw the story first.
        db.execute("UPDATE items SET summary = ? WHERE key = ? AND summary = ''", (it["summary"], it["key"]))
    return cur.rowcount == 1


def refusals(db, domain):
    r = db.execute("SELECT refusals FROM domains WHERE domain = ?", (domain,)).fetchone()
    return r["refusals"] if r else 0


def refused(db, domain):
    db.execute("INSERT INTO domains (domain, refusals) VALUES (?, 1)"
               " ON CONFLICT(domain) DO UPDATE SET refusals = refusals + 1", (domain,))
