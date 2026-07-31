"""Reads RSS and turns entries into article drafts.

Only title, summary and link are kept, and the reader goes to the original
site. Article bodies are never stored, which respects the terms of the feeds
and is why the ingestion does not scrape.
"""

import html
import re
from dataclasses import dataclass
from datetime import UTC, datetime

import feedparser

_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class ArticleDraft:
    source_id: int
    title: str
    summary: str
    url: str
    published_at: str


def clean_summary(raw: str | None) -> str:
    """Strips markup and collapses whitespace.

    Entities are decoded before tags are stripped, so a feed that double
    encodes its markup (`&lt;p&gt;`) loses the tag instead of showing it as
    literal text on the card.
    """
    if not raw:
        return ""

    text = html.unescape(raw)
    text = _TAG.sub(" ", text)
    return _WHITESPACE.sub(" ", text).strip()


def _published_at(entry, now: datetime) -> str:
    """feedparser already normalizes the parsed time to UTC.

    Ranking decays by age, so an article landing in the wrong timezone would be
    hours too old or too fresh against every other source.
    """
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    moment = datetime(*parsed[:6], tzinfo=UTC) if parsed else now
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_feed(raw_xml: bytes, source_id: int, now: datetime) -> list[ArticleDraft]:
    """Parses one feed. A broken feed yields nothing rather than raising.

    The hourly run reads several portals, and one of them serving garbage must
    not take the other five down with it.
    """
    parsed = feedparser.parse(raw_xml)

    drafts = []
    for entry in parsed.entries:
        url = (entry.get("link") or "").strip()
        if not url:
            continue

        title = clean_summary(entry.get("title"))
        if not title:
            continue

        summary = clean_summary(entry.get("summary") or entry.get("description"))
        drafts.append(ArticleDraft(source_id, title, summary, url, _published_at(entry, now)))

    return drafts


def dedupe_by_url(drafts: list[ArticleDraft]) -> list[ArticleDraft]:
    """Keeps the first draft seen for each URL.

    This only catches the same URL twice. Two portals covering the same event
    under different URLs is a different problem, and clustering solves it.
    """
    seen = set()
    unique = []
    for draft in drafts:
        if draft.url in seen:
            continue
        seen.add(draft.url)
        unique.append(draft)
    return unique
