"""Aggregate mentions into ranked terms per window. Score = number of DISTINCT outlets."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .extract import Mention
from .normalize import WordLists

WINDOWS = {"6h": 6 * 3600, "24h": 24 * 3600, "7d": 7 * 24 * 3600}
TOP_N = 60
MIN_OUTLETS = 2
REFS_PER_OUTLET = 5


@dataclass
class TermInfo:
    surfaces: Counter = field(default_factory=Counter)
    votes: Counter = field(default_factory=Counter)


def term_meta(items: list[dict], mentions: list[list[Mention]], wl: WordLists) -> dict[str, dict]:
    """Label + category + crime flag for every term key, from ALL mentions in the store."""
    info: dict[str, TermInfo] = defaultdict(TermInfo)
    for ms in mentions:
        for m in ms:
            ti = info[m.key]
            ti.surfaces[m.surface] += 1
            if m.category:
                ti.votes[m.category] += 1
    meta = {}
    for k, ti in info.items():
        canon = wl.canonical.get(k)
        if canon:
            label, cat = canon["label"], canon["category"]
        else:
            # Prefer a form that isn't capitalised only because it starts the headline.
            label = _best_surface(ti.surfaces)
            cat = None
        if not cat:
            cat = ti.votes.most_common(1)[0][0] if ti.votes else "topic"
        meta[k] = {"label": label, "category": cat, "crime": wl.is_crime(k)}
    return meta


def _best_surface(c: Counter) -> str:
    forms = c.most_common()
    lower = [(f, n) for f, n in forms if f[:1].islower()]
    # If a lowercase form is at least a third as common, the capital was just sentence case.
    if lower and lower[0][1] * 3 >= forms[0][1]:
        return lower[0][0]
    return forms[0][0]


def outlets_by_term(items: list[dict], mentions: list[list[Mention]], start: float, end: float):
    """term key -> {outlet id -> [item indexes]} for items with start <= ts < end."""
    acc: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for idx, (it, ms) in enumerate(zip(items, mentions)):
        if start <= it["ts"] < end:
            for m in ms:
                acc[m.key][it["o"]].append(idx)
    return acc


def rank(acc: dict[str, dict[str, list[int]]], items: list[dict], top_n: int = TOP_N,
         min_outlets: int = MIN_OUTLETS) -> list[tuple[str, int, int]]:
    """[(key, distinct outlets, articles)] best first. Ties: more articles, then most recent."""
    rows = []
    for k, by_outlet in acc.items():
        n_out = len(by_outlet)
        if n_out < min_outlets:
            continue
        n_art = sum(len(v) for v in by_outlet.values())
        latest = max(items[i]["ts"] for v in by_outlet.values() for i in v)
        rows.append((-n_out, -n_art, -latest, k))
    rows.sort()
    return [(k, -a, -b) for a, b, _, k in rows[:top_n]]


def window_terms(items, mentions, meta, now: float, window: str, prev_scores: dict[str, int] | None):
    """Build the output list for one window.

    prev_scores: distinct-outlet counts for the previous window of the same length,
    or None when that window isn't covered by our data (trend unknown).
    """
    span = WINDOWS[window]
    acc = outlets_by_term(items, mentions, now - span, now + 1)
    terms, refs_used = [], set()
    for k, n_out, n_art in rank(acc, items):
        refs = []
        for oid, idxs in acc[k].items():
            idxs = sorted(idxs, key=lambda i: -items[i]["ts"])[:REFS_PER_OUTLET]
            refs.extend(items[i]["id"] for i in idxs)
        refs_used.update(refs)
        prev = None if prev_scores is None else prev_scores.get(k, 0)
        terms.append({
            "key": k,
            **meta[k],
            "score": n_out,
            "articles": n_art,
            "prev": prev,
            "trend": None if prev is None else n_out - prev,
            "refs": refs,
        })
    return terms, refs_used


def scores_in(items, mentions, start: float, end: float) -> dict[str, int]:
    return {k: len(v) for k, v in outlets_by_term(items, mentions, start, end).items()}
