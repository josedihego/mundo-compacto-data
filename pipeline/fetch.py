"""Fetch and parse RSS/Atom/RDF feeds. Keeps only headline, link and time."""
from __future__ import annotations

import concurrent.futures as cf
import email.utils
import html
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

USER_AGENT = "Mozilla/5.0 (compatible; MundoCompacto/0.1; news word wall)"
TIMEOUT = 20
TAG_RE = re.compile(r"<[^>]+>")


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _parse_xml(raw: bytes) -> ET.Element:
    try:
        return ET.fromstring(raw)
    except ET.ParseError:
        pass
    # Some feeds (e.g. UOL) are Latin-1 with no XML declaration.
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    return ET.fromstring(re.sub(r"^\s*<\?xml[^>]*\?>", "", text))


def parse_date(s: str | None) -> float | None:
    if not s:
        return None
    s = s.strip()
    try:
        return email.utils.parsedate_to_datetime(s).timestamp()
    except (TypeError, ValueError, IndexError):
        pass
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()
    except ValueError:
        return None


def clean_text(s: str | None) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", s))).strip()


def clean_link(link: str) -> str:
    link = link.strip()
    if "*http" in link:  # Folha's redirector: .../rss091/*https://www1.folha...
        link = link[link.index("*http") + 1:]
    return link


def parse_feed(raw: bytes) -> list[dict]:
    """Return [{title, link, published}] — description/body is deliberately ignored."""
    root = _parse_xml(raw)
    out = []
    for el in root.iter():
        if _local(el.tag) not in ("item", "entry"):
            continue
        title = link = date = None
        for child in el:
            name = _local(child.tag)
            if name == "title":
                title = clean_text(child.text)
            elif name == "link":
                href = child.get("href")
                if href and child.get("rel", "alternate") == "alternate":
                    link = href
                elif child.text and not link:
                    link = child.text
            elif name in ("pubdate", "published", "date", "updated") and not date:
                date = child.text
        if not link:
            link = el.get("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about")
        if title and link:
            out.append({"title": title, "link": clean_link(link), "published": parse_date(date)})
    return out


def fetch_all(feeds: list[dict]) -> tuple[list[dict], dict[str, int | str]]:
    """Fetch every feed in parallel. status[id] = item count, or an error string."""
    items, status = [], {}

    def one(feed):
        return parse_feed(fetch(feed["url"]))

    with cf.ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(one, f): f["id"] for f in feeds}
        for fut in cf.as_completed(futures):
            oid = futures[fut]
            try:
                got = fut.result()
                status[oid] = len(got) if got else "error: feed returned no items"
                for it in got:
                    items.append({**it, "outlet": oid})
            except Exception as e:  # noqa: BLE001 — one bad feed must not break the run
                status[oid] = f"error: {type(e).__name__}: {e}"[:200]
    return items, status
