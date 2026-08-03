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

# The invitation a portal staples to the end of its own summary. One portal ends
# 377 of its articles with a variant of "Clique aqui para seguir o canal do g1
# [city] no WhatsApp", which is why `canal` reached 506 documents and `clique`
# 446, both above every real subject in the Portuguese corpus.
#
# Cut here rather than in the discard list, because the words themselves are not
# the problem: `whatsapp` names a genuine subject in 10 of its 205 articles, and
# banning the term to be rid of the other 195 would throw those away too.
#
# Scoped to the sentence, and the sentence is what bounds it rather than a
# character count. A cap looked safer and was not: the clause is not always
# closed by a full stop, and a cap that runs out mid-word leaves the tail of that
# word behind as a term. Running to the next terminator instead is correct even
# when the clause holds two invitations, which is the shape one portal uses.
_PROMO = re.compile(
    r"[✅\U0001F4F1\U0001F449\U0001F4E2➡️\s:]*"
    r"(?:clique aqui|siga o canal|baixe o app|assine a newsletter|"
    r"veja mais not[íi]cias|leia tamb[ée]m)"
    r"[^.!?]*[.!?]?",
    re.IGNORECASE,
)

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
    # Which spaCy model reduces this to lemmas. It travels with the draft rather
    # than being looked up later, because by the time `prepare` runs the source
    # is an integer id and the language would have to be joined back out.
    language: str = "pt"


def strip_promotion(text: str) -> str:
    """Removes the portal's invitations and collapses the whitespace they leave.

    Separate from `clean_summary` because the summaries already in the corpus
    were stored before this rule existed, and they carry the invitation in the
    text the card shows. `reprocess_terms` runs this over them, and it must not
    also unescape entities or strip tags a second time on text that has already
    had both done to it.
    """
    return _WHITESPACE.sub(" ", _PROMO.sub(" ", text)).strip()


def clean_summary(raw: str | None) -> str:
    """Strips markup, removes the promotional tail, and collapses whitespace.

    Entities are decoded before tags are stripped, so a feed that double
    encodes its markup (`&lt;p&gt;`) loses the tag instead of showing it as
    literal text on the card.
    """
    if not raw:
        return ""

    text = html.unescape(raw)
    text = _TAG.sub(" ", text)
    text = strip_promotion(text)

    if len(text) <= SUMMARY_MAX_CHARS:
        return text

    # Cut on a word boundary. Half a word lemmatizes to something that is not a
    # word, and the card shows that text to the reader as an explanation.
    cut = text[:SUMMARY_MAX_CHARS]
    boundary = cut.rfind(" ")
    return cut[:boundary].strip() if boundary > 0 else cut.strip()


def _summary_of(entry) -> str:
    """The entry's text, wherever this feed decided to put it.

    `description` is where almost every portal writes it, and Tecmundo writes
    nothing there at all: its forty items arrived with empty summaries until
    `content` was checked, which is where its text actually lives. A card with a
    headline and no text is a card that lost a third of what it had to say, and
    the article's terms lose the whole body with it.
    """
    for value in (entry.get("summary"), entry.get("description")):
        cleaned = clean_summary(value)
        if cleaned:
            return cleaned

    # feedparser hands `content` back as a list of alternatives, richest first.
    for block in entry.get("content") or ():
        cleaned = clean_summary(block.get("value"))
        if cleaned:
            return cleaned

    return ""


def _published_at(entry, now: datetime) -> str:
    """feedparser already normalizes the parsed time to UTC.

    Ranking decays by age, so an article landing in the wrong timezone would be
    hours too old or too fresh against every other source.
    """
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    moment = datetime(*parsed[:6], tzinfo=UTC) if parsed else now
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_feed(
    raw_xml: bytes, source_id: int, now: datetime, language: str = "pt"
) -> list[ArticleDraft]:
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

        summary = _summary_of(entry)
        drafts.append(
            ArticleDraft(source_id, title, summary, url, _published_at(entry, now), language)
        )

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
