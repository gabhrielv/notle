"""Orchestrates one ingestion run.

The decision of what to store is a pure function over the drafts and the URLs
already in the corpus. The writing is a thin layer on top. Keeping them apart
is what lets the part with a knowable right answer be tested without a network
or a credential.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

from ingest.clustering import assign_cluster
from ingest.feeds import ArticleDraft, dedupe_by_url, parse_feed
from ingest.normalize import lemmatize, term_frequencies
from ingest.sources import SOURCES
from ingest.store import D1Client

USER_AGENT = "notle/0.1 (+https://github.com/gabhrielv/notle)"
FETCH_TIMEOUT = 25.0


@dataclass(frozen=True)
class PreparedArticle:
    draft: ArticleDraft
    term_frequencies: dict[str, float]


@dataclass(frozen=True)
class IngestionPlan:
    articles: list[PreparedArticle] = field(default_factory=list)
    document_counts: Counter = field(default_factory=Counter)

    @property
    def total_docs_delta(self) -> int:
        return len(self.articles)


def prepare(drafts: list[ArticleDraft], known_urls: set[str]) -> IngestionPlan:
    """Works out what this run should store.

    Drops what the corpus already has, normalizes the rest, and counts how many
    documents each term appears in.
    """
    articles: list[PreparedArticle] = []
    document_counts: Counter = Counter()

    for draft in drafts:
        if draft.url in known_urls:
            continue

        frequencies = term_frequencies(lemmatize(f"{draft.title}. {draft.summary}"))
        if not frequencies:
            # An empty vector has cosine zero against every profile forever, so
            # the row and its cluster could never rank.
            continue

        articles.append(PreparedArticle(draft, frequencies))
        document_counts.update(frequencies.keys())

    return IngestionPlan(articles=articles, document_counts=document_counts)


def fetch_drafts(sources=SOURCES, now: datetime | None = None, get=None) -> list[ArticleDraft]:
    """Reads every feed. A portal that fails is skipped, not fatal."""
    now = now or datetime.now(UTC)
    get = get or _http_get

    drafts: list[ArticleDraft] = []
    for source_id, source in enumerate(sources, start=1):
        try:
            drafts.extend(parse_feed(get(source.feed_url), source_id, now))
        except Exception:
            continue

    return dedupe_by_url(drafts)


def _http_get(url: str) -> bytes:
    response = httpx.get(
        url,
        timeout=FETCH_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )
    response.raise_for_status()
    return response.content


def known_urls(client: D1Client, urls: list[str]) -> set[str]:
    """Asks the corpus which of these URLs it already holds."""
    found: set[str] = set()
    # D1 caps bound parameters at 100 per query.
    for start in range(0, len(urls), 100):
        window = urls[start : start + 100]
        placeholders = ", ".join("?" * len(window))
        rows = client.query(
            f"SELECT url FROM articles WHERE url IN ({placeholders})",
            window,
        )
        found.update(row["url"] for row in rows)
    return found


def store(client: D1Client, plan: IngestionPlan, now: datetime) -> None:
    """Writes a prepared plan to the corpus."""
    fetched_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    for article in plan.articles:
        draft = article.draft

        cluster_id = assign_cluster(draft, article.term_frequencies, [])
        if cluster_id is None:
            client.query(
                "INSERT INTO clusters (first_seen_at, size) VALUES (?, 1)",
                [draft.published_at],
            )
            cluster_id = client.query("SELECT last_insert_rowid() AS id")[0]["id"]

        client.query(
            "INSERT OR IGNORE INTO articles "
            "(source_id, cluster_id, title, summary, url, published_at, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                draft.source_id,
                cluster_id,
                draft.title,
                draft.summary,
                draft.url,
                draft.published_at,
                fetched_at,
            ],
        )
        rows = client.query("SELECT id FROM articles WHERE url = ?", [draft.url])
        if not rows:
            continue
        article_id = rows[0]["id"]

        client.insert_many(
            "article_terms",
            ("article_id", "term", "tf"),
            [(article_id, term, tf) for term, tf in article.term_frequencies.items()],
        )

    for term, count in plan.document_counts.items():
        client.query(
            "INSERT INTO terms (term, doc_count) VALUES (?, ?) "
            "ON CONFLICT(term) DO UPDATE SET doc_count = doc_count + ?",
            [term, count, count],
        )

    client.query(
        "UPDATE corpus_stats SET total_docs = total_docs + ? WHERE id = 1",
        [plan.total_docs_delta],
    )


def run(client: D1Client | None = None, now: datetime | None = None) -> IngestionPlan:
    """One full pass: read the feeds, work out what is new, store it."""
    client = client or D1Client.from_env()
    now = now or datetime.now(UTC)

    drafts = fetch_drafts(now=now)
    plan = prepare(drafts, known_urls(client, [d.url for d in drafts]))
    store(client, plan, now)
    return plan


if __name__ == "__main__":
    result = run()
    print(f"{result.total_docs_delta} artigos novos, {len(result.document_counts)} termos tocados")
