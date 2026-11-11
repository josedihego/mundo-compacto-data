#!/usr/bin/env python3
"""Hourly build: fetch feeds -> update 7-day store -> extract terms -> data/latest.json.

    python -m pipeline.build [--state state] [--out data/latest.json]

State (not published):
  state/store.json        headlines only: outlet, headline, link, time — 7 days
  state/history.json      per-term outlet counts of the 7-day window, for its trend
  state/feed_health.json  consecutive failures per feed
  state/feed_alerts.json  feeds to open / close GitHub issues for (read by the workflow)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

from .extract import extract
from .fetch import fetch_all
from .normalize import CONFIG, WordLists
from .score import WINDOWS, scores_in, term_meta, window_terms

ROOT = Path(__file__).resolve().parent.parent
RETENTION = 7 * 24 * 3600
HISTORY_KEEP = 8 * 24 * 3600
HISTORY_TOP = 400
HISTORY_TOLERANCE = 3 * 3600
FAIL_ALERT_AFTER = 3   # consecutive failed runs before an issue is opened


def item_id(outlet: str, title: str) -> str:
    norm = re.sub(r"\W+", " ", title.lower()).strip()
    return hashlib.sha1(f"{outlet}|{norm}".encode()).hexdigest()[:12]


def load_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def update_store(store: dict, fresh: list[dict], now: float) -> dict:
    items = store.get("items", {})
    for it in fresh:
        iid = item_id(it["outlet"], it["title"])
        if iid in items:
            continue
        ts = it["published"]
        if ts is None or ts > now + 3600:   # missing or bogus future date -> first seen
            ts = now
        items[iid] = {"o": it["outlet"], "t": it["title"], "u": it["link"], "ts": int(ts)}
    cutoff = now - RETENTION
    return {"since": store.get("since", int(now)),
            "items": {k: v for k, v in items.items() if v["ts"] >= cutoff}}


def update_health(health: dict, status: dict, feeds: list[dict], now: float):
    """Returns (health, alerts). Alerts list feeds failing >= FAIL_ALERT_AFTER runs, and recoveries."""
    by_id = {f["id"]: f for f in feeds}
    failing, recovered = [], []
    for oid, st in status.items():
        h = health.get(oid, {"fails": 0})
        if isinstance(st, int):
            if h.get("fails", 0) >= FAIL_ALERT_AFTER:
                recovered.append(oid)
            h = {"fails": 0, "last_ok": int(now)}
        else:
            h = {**h, "fails": h.get("fails", 0) + 1, "last_error": st}
            if h["fails"] >= FAIL_ALERT_AFTER:
                failing.append({"id": oid, "name": by_id[oid]["name"], "url": by_id[oid]["url"],
                                "fails": h["fails"], "error": st})
        health[oid] = h
    return health, {"failing": failing,
                    "recovered": [{"id": o, "name": by_id[o]["name"]} for o in recovered]}


def prev_7d(history: list[dict], now: float) -> dict[str, int] | None:
    target = now - WINDOWS["7d"]
    best = min(history, key=lambda s: abs(s["ts"] - target), default=None)
    if best and abs(best["ts"] - target) <= HISTORY_TOLERANCE:
        return best["scores"]
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default=str(ROOT / "state"))
    ap.add_argument("--out", default=str(ROOT / "data" / "latest.json"))
    args = ap.parse_args()
    state, out = Path(args.state), Path(args.out)

    now = time.time()
    feeds = json.loads((CONFIG / "feeds.json").read_text(encoding="utf-8"))
    wl = WordLists.load()

    fresh, status = fetch_all(feeds)
    for oid in sorted(status):
        print(f"  {oid:14} {status[oid]}", file=sys.stderr)

    health, alerts = update_health(load_json(state / "feed_health.json", {}), status, feeds, now)
    save_json(state / "feed_health.json", health)
    save_json(state / "feed_alerts.json", alerts)

    ok = sum(isinstance(v, int) for v in status.values())
    if ok < len(feeds) // 2:
        print(f"Only {ok}/{len(feeds)} feeds succeeded; keeping the previous output.", file=sys.stderr)
        return 1

    store = update_store(load_json(state / "store.json", {}), fresh, now)
    save_json(state / "store.json", store)

    items = [{"id": k, **v} for k, v in store["items"].items()]
    t0 = time.time()
    mentions = extract([it["t"] for it in items], wl)
    print(f"extracted terms from {len(items)} headlines in {time.time() - t0:.1f}s", file=sys.stderr)
    meta = term_meta(items, mentions, wl)

    history = [s for s in load_json(state / "history.json", []) if s["ts"] >= now - HISTORY_KEEP]
    windows, used = {}, set()
    for name, span in WINDOWS.items():
        if name == "7d":
            prev = prev_7d(history, now)
        elif now - 2 * span >= store["since"]:
            prev = scores_in(items, mentions, now - 2 * span, now - span)
        else:
            prev = None  # not enough data yet to know the previous window
        terms, refs = window_terms(items, mentions, meta, now, name, prev)
        windows[name] = {"span_hours": span // 3600, "terms": terms}
        used |= refs

    week = scores_in(items, mentions, now - WINDOWS["7d"], now + 1)
    top = dict(sorted(week.items(), key=lambda kv: -kv[1])[:HISTORY_TOP])
    history.append({"ts": int(now), "scores": top})
    save_json(state / "history.json", history)

    by_id = {it["id"]: it for it in items}
    save_json(out, {
        "generated_at": int(now),
        "windows": windows,
        "headlines": {i: {k: by_id[i][k] for k in ("o", "t", "u", "ts")} for i in sorted(used)},
        "outlets": {f["id"]: {"name": f["name"], "ok": isinstance(status.get(f["id"]), int)}
                    for f in feeds},
    })
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
