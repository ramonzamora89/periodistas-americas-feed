#!/usr/bin/env python3
"""Fetch, normalize, dedupe and publish the journalist-attacks feed.

Reads config/sources.yaml, fetches every active RSS/Atom source, merges
duplicate coverage of the same case (exact link match + fuzzy title match),
and writes docs/data/feed.json + docs/data/status.json for the static site.
"""

from __future__ import annotations

import calendar
import hashlib
import html
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "sources.yaml"
FEED_OUT_PATH = ROOT / "docs" / "data" / "feed.json"
STATUS_OUT_PATH = ROOT / "docs" / "data" / "status.json"

USER_AGENT = "PeriodistasAmericasFeedBot/1.0 (+https://github.com/)"
REQUEST_TIMEOUT_SECONDS = 15

MAX_AGE_DAYS = 90
MAX_ITEMS = 500

FUZZY_WINDOW_HOURS = 72
FUZZY_JACCARD_THRESHOLD = 0.5
FUZZY_MIN_TOKENS = 4

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "mc_cid", "mc_eid",
}

STOPWORDS = {
    "journalist", "periodista", "periodistas", "reportero", "reportera",
    "killed", "murdered", "asesinado", "asesinada", "muere", "murio",
    "died", "attack", "attacked", "ataque", "atacado", "atacada",
    "detained", "detenido", "detenida", "the", "a", "an", "de", "en",
    "el", "la", "los", "las", "por", "for", "in", "on", "and", "y",
    "con", "with", "que", "es", "un", "una", "to", "of", "su", "sus",
}

# Un item entra a la pestaña "migración" si su título/resumen matchea alguna
# de estas palabras clave, sin importar la category de su fuente — así un
# caso de censura a un periodista que cubre migración (category
# libertad_prensa) también aparece ahí.
MIGRATION_KEYWORDS = re.compile(
    r"\b("
    r"migrant[s]?|migration|immigra(nt|tion)[s]?|asylum|refugee[s]?|"
    r"deport(ed|ation|ing)?|border crossing|migrant caravan|"
    r"migrante[s]?|migraci[oó]n|inmigra(nte|ci[oó]n)[s]?|asilo|"
    r"refugiado[s]?|deportaci[oó]n|deportad[oa][s]?|frontera|"
    r"caravana migrante"
    r")\b",
    re.IGNORECASE,
)


@dataclass
class Source:
    id: str
    name: str
    url: str
    language: str
    country: str | None
    priority: int
    category: str
    active: bool


@dataclass
class Item:
    id: str
    title: str
    link: str
    published: str
    published_ts: float
    summary: str
    source: str
    source_id: str
    language: str
    country: str | None
    priority: int
    category: str
    topics: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    also_reported_by: list[dict] = field(default_factory=list)


def load_sources() -> list[Source]:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    sources = []
    for entry in raw.get("sources", []):
        if not entry.get("active", False):
            continue
        sources.append(
            Source(
                id=entry["id"],
                name=entry["name"],
                url=entry["url"],
                language=entry["language"],
                country=entry.get("country"),
                priority=int(entry["priority"]),
                category=entry["category"],
                active=True,
            )
        )
    return sources


def canonicalize_link(link: str) -> str:
    parts = urlsplit(link)
    scheme = "https"
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/")
    query_pairs = [
        (k, v) for k, v in parse_qsl(parts.query) if k.lower() not in TRACKING_PARAMS
    ]
    query = urlencode(sorted(query_pairs))
    return urlunsplit((scheme, netloc, path, query, ""))


def strip_html(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<[^<]+?>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_published(entry) -> tuple[str, float]:
    struct = entry.get("published_parsed") or entry.get("updated_parsed")
    if struct:
        ts = calendar.timegm(struct)
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.isoformat(), ts
    now = datetime.now(tz=timezone.utc)
    return now.isoformat(), now.timestamp()


def normalize_entries(source: Source, feed) -> list[Item]:
    items = []
    for entry in feed.entries:
        link = entry.get("link", "")
        if not link:
            continue
        canonical = canonicalize_link(link)
        item_id = hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:16]
        published, published_ts = parse_published(entry)
        summary = strip_html(entry.get("summary") or entry.get("description") or "")
        if len(summary) > 300:
            summary = summary[:297].rstrip() + "..."
        tags = [t.get("term") for t in entry.get("tags", []) if t.get("term")]
        title = strip_html(entry.get("title", ""))

        topics = [source.category]
        if MIGRATION_KEYWORDS.search(f"{title} {summary}"):
            topics.append("migracion")

        items.append(
            Item(
                id=item_id,
                title=title,
                link=link,
                published=published,
                published_ts=published_ts,
                summary=summary,
                source=source.name,
                source_id=source.id,
                language=source.language,
                country=source.country,
                priority=source.priority,
                category=source.category,
                topics=topics,
                tags=tags,
            )
        )
    return items


def dedupe_exact(items: list[Item]) -> list[Item]:
    items = sorted(items, key=lambda i: i.published_ts)
    by_id: dict[str, Item] = {}
    for item in items:
        existing = by_id.get(item.id)
        if existing is None:
            by_id[item.id] = item
        else:
            existing.also_reported_by.append({"source": item.source, "link": item.link})
    return list(by_id.values())


def normalize_title_tokens(title: str) -> tuple[set[str], set[str]]:
    notable = {
        tok for tok in re.findall(r"[A-Za-zÀ-ÿ]{4,}", title) if tok[0].isupper()
    }
    normalized = unicodedata.normalize("NFKD", title.lower())
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    tokens = {tok for tok in normalized.split() if tok not in STOPWORDS}
    return tokens, notable


def dedupe_fuzzy(items: list[Item]) -> list[Item]:
    items = sorted(items, key=lambda i: i.published_ts)
    token_cache = {item.id: normalize_title_tokens(item.title) for item in items}
    merged_away: set[str] = set()

    for i, item_a in enumerate(items):
        if item_a.id in merged_away:
            continue
        tokens_a, notable_a = token_cache[item_a.id]
        if len(tokens_a) < FUZZY_MIN_TOKENS:
            continue
        for item_b in items[i + 1:]:
            if item_b.id in merged_away or item_b.id == item_a.id:
                continue
            if abs(item_b.published_ts - item_a.published_ts) > FUZZY_WINDOW_HOURS * 3600:
                continue
            tokens_b, notable_b = token_cache[item_b.id]
            if len(tokens_b) < FUZZY_MIN_TOKENS:
                continue

            union = tokens_a | tokens_b
            if not union:
                continue
            jaccard = len(tokens_a & tokens_b) / len(union)
            if jaccard < FUZZY_JACCARD_THRESHOLD:
                continue
            if not (notable_a & notable_b):
                continue

            primary, secondary = (
                (item_a, item_b)
                if (item_a.priority, item_a.published_ts) <= (item_b.priority, item_b.published_ts)
                else (item_b, item_a)
            )
            primary.also_reported_by.append({"source": secondary.source, "link": secondary.link})
            primary.also_reported_by.extend(secondary.also_reported_by)
            merged_away.add(secondary.id)
            if secondary.id == item_a.id:
                break

    return [item for item in items if item.id not in merged_away]


def fetch_source(source: Source) -> tuple[list[Item], dict]:
    try:
        response = requests.get(
            source.url,
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
        if parsed.bozo and not parsed.entries:
            raise ValueError(f"unparseable feed: {parsed.bozo_exception}")
        items = normalize_entries(source, parsed)
        return items, {
            "id": source.id,
            "name": source.name,
            "ok": True,
            "items_fetched": len(items),
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 - deliberately broad, one bad source shouldn't abort the run
        return [], {
            "id": source.id,
            "name": source.name,
            "ok": False,
            "items_fetched": 0,
            "error": str(exc),
        }


def item_to_dict(item: Item) -> dict:
    return {
        "id": item.id,
        "title": item.title,
        "link": item.link,
        "published": item.published,
        "summary": item.summary,
        "source": item.source,
        "source_id": item.source_id,
        "language": item.language,
        "country": item.country,
        "category": item.category,
        "topics": item.topics,
        "tags": item.tags,
        "also_reported_by": item.also_reported_by,
    }


def main() -> int:
    sources = load_sources()
    all_items: list[Item] = []
    status_entries = []

    for source in sources:
        items, status = fetch_source(source)
        all_items.extend(items)
        status_entries.append(status)

    all_items = dedupe_exact(all_items)
    all_items = dedupe_fuzzy(all_items)

    cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=MAX_AGE_DAYS)).timestamp()
    all_items = [item for item in all_items if item.published_ts >= cutoff]
    all_items.sort(key=lambda i: i.published_ts, reverse=True)
    all_items = all_items[:MAX_ITEMS]

    now_iso = datetime.now(tz=timezone.utc).isoformat()

    FEED_OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with FEED_OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "generated_at": now_iso,
                "count": len(all_items),
                "items": [item_to_dict(item) for item in all_items],
            },
            f,
            ensure_ascii=False,
            indent=1,
        )

    with STATUS_OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump({"last_run": now_iso, "sources": status_entries}, f, ensure_ascii=False, indent=1)

    active_ok = [s for s in status_entries if s["ok"]]
    if sources and not active_ok:
        print("ERROR: all active sources failed", file=sys.stderr)
        return 1

    print(f"Wrote {len(all_items)} items from {len(active_ok)}/{len(sources)} sources.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
