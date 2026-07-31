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

# Some portals put the entire article body in <description>. Measured against
# the live feeds: G1 averages 5690 characters per item and Agencia Brasil 2875,
# while Folha, BBC, CNN and Poder360 sit between 125 and 343.
#
# That gap is not cosmetic. Term frequencies are normalized to sum to one, so an
# uncapped G1 item spreads its weight across 243 terms at 0.4% each while a
# Poder360 item puts 6.7% on each of 15. Every G1 story would then rank low for
# a reason that has nothing to do with what the reader likes. It is the same
# invisible source bias the architecture rejects for dwell time, arriving from
# the opposite direction.
#
# The cap sits just above the longest genuine summary observed (520 characters),
# so real summaries pass through untouched and only bodies get trimmed.
SUMMARY_MAX_CHARS = 600


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
    text = _WHITESPACE.sub(" ", text).strip()

    if len(text) <= SUMMARY_MAX_CHARS:
        return text

    # Cut on a word boundary. Half a word lemmatizes to something that is not a
    # word, and the card shows that text to the reader as an explanation.
    cut = text[:SUMMARY_MAX_CHARS]
    boundary = cut.rfind(" ")
    return cut[:boundary].strip() if boundary > 0 else cut.strip()


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
