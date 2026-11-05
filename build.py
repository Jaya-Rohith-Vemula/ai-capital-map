#!/usr/bin/env python3
"""Draw out/map.html from the ledger: one file, works offline.

    python3 build.py           # rebuild
    python3 build.py --open    # rebuild and open it in the browser
"""

import datetime as dt
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))


def read(*p):
    with open(os.path.join(ROOT, *p)) as f:
        return f.read()


def build():
    cfg = json.loads(read("config.json"))
    cdoc = json.loads(read("data", "companies.json"))
    ddoc = json.loads(read("data", "deals.json"))
    runs_dir = os.path.join(ROOT, "runs")
    runs = []
    for name in sorted(os.listdir(runs_dir)) if os.path.isdir(runs_dir) else []:
        if name.endswith(".json"):
            r = json.loads(read("runs", name))
            if not r.get("completed", True):
                continue
            runs.append({k: r.get(k) for k in ("id", "at", "since", "until", "candidates", "new_deals", "updated_deals", "new_companies")})
    data = {
        "layers": cdoc["layers"], "companies": cdoc["companies"], "deals": ddoc["deals"], "runs": runs,
        "holdings": cfg.get("holdings", []), "built_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    # </ would end the inline script early if a headline ever contained </script>.
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = read("viewer.html").replace("/*__CYTOSCAPE__*/", read("vendor", "cytoscape.min.js"), 1).replace("/*__DATA__*/", blob, 1)
    os.makedirs(os.path.join(ROOT, "out"), exist_ok=True)
    path = os.path.join(ROOT, "out", "map.html")
    with open(path, "w") as f:
        f.write(html)
    return path


if __name__ == "__main__":
    p = build()
    print(p)
    if "--open" in sys.argv:
        subprocess.run(["open", p])
