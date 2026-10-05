"""Learn how long public attention really lasted for each past event, from Wikipedia pageviews.

For every event in crowdsim/knowledge/events.yaml that has a `wiki: {title, date}` entry (pageview
data exists from July 2015 on), this downloads daily views from 14 days before to 120 days after,
measures the peak day and how fast attention decayed, and writes
crowdsim/knowledge/attention_learned.json. The simulator then prefers these measured numbers over
the hand-coded ones when it borrows timing from history.

    python tools/learn_attention.py            # all events with a wiki title
    python tools/learn_attention.py bud_light_2023 svb_2023

Free, no key. Wikimedia asks for a descriptive User-Agent; set CROWDSIM_CONTACT to your email/site.
Add your own events (any article title + date) to events.yaml and rerun to grow the memory.
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.parse
import urllib.request

import numpy as np
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KNOW = os.path.join(ROOT, "crowdsim", "knowledge")
API = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia.org/all-access/user/{}/daily/{}/{}"


def fetch(title, date, before=14, after=120):
    d0 = dt.date.fromisoformat(str(date)) - dt.timedelta(days=before)
    d1 = dt.date.fromisoformat(str(date)) + dt.timedelta(days=after)
    url = API.format(urllib.parse.quote(title, safe=""), d0.strftime("%Y%m%d"), d1.strftime("%Y%m%d"))
    ua = f"crowdsim-attention-learner/1.0 ({os.getenv('CROWDSIM_CONTACT', 'https://github.com')})"
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=30) as r:
        items = json.loads(r.read())["items"]
    return np.array([it["views"] for it in items], float), before


def measure(views, before):
    """Peak day (relative to the event date) and attention half-life in days.

    Baseline = median of the pre-event days. Half-life comes from a log-linear fit of the excess
    over baseline during the 30 days after the peak (robust to day-to-day noise); falls back to
    the first day the excess drops below half of the peak excess."""
    base = float(np.median(views[:max(before - 2, 3)]))
    excess = np.clip(views - base, 0, None)
    pk = int(np.argmax(excess[before - 2:])) + before - 2
    peak = excess[pk]
    if peak <= 0:
        return None
    tail = excess[pk:pk + 31]
    ok = tail > peak * 0.02
    days = np.arange(tail.size)[ok]
    if days.size >= 5:
        slope = np.polyfit(days, np.log(tail[ok]), 1)[0]
        half = float(np.log(2) / -slope) if slope < 0 else 60.0
    else:
        below = np.flatnonzero(tail < peak / 2)
        half = float(below[0]) if below.size else 30.0
    curve = (excess[before:before + 60] / peak).round(3).tolist()
    return {"peak_day": pk - before, "halflife_days": round(min(max(half, 0.5), 60.0), 1),
            "peak_ratio": round(float(views[pk] / max(base, 1)), 1), "curve": curve}


def main(ids):
    with open(os.path.join(KNOW, "events.yaml")) as f:
        events = yaml.safe_load(f)["events"]
    out_path = os.path.join(KNOW, "attention_learned.json")
    learned = json.load(open(out_path)) if os.path.exists(out_path) else {}
    for e in events:
        w = e.get("wiki")
        if not w or (ids and e["id"] not in ids):
            continue
        if str(w["date"]) < "2015-07-15":
            print(f"skip {e['id']}: pageviews start July 2015")
            continue
        try:
            views, before = fetch(w["title"], w["date"])
            m = measure(views, before)
            if m:
                m["source"] = f"en.wikipedia.org/{w['title']}"
                learned[e["id"]] = m
                print(f"{e['id']:28s} peak day {m['peak_day']:3d}  half-life {m['halflife_days']:5.1f} d  "
                      f"peak {m['peak_ratio']}x baseline  (coded guess was {e['outcome']['halflife_days']} d)")
        except Exception as ex:
            print(f"{e['id']:28s} failed: {ex}")
        time.sleep(0.3)
    with open(out_path, "w") as f:
        json.dump(learned, f, indent=1)
    print(f"wrote {out_path} ({len(learned)} events)")


if __name__ == "__main__":
    main(set(sys.argv[1:]))
