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
from ingest.store import MAX_BOUND_PARAMS, D1Client

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


def ensure_sources(client, sources=SOURCES) -> dict[str, int]:
    """Registers any feed the corpus does not know yet.

    Returns feed_url to the id the database actually assigned. The id has to
    come back from the database rather than from the feed's position in
    `sources`: articles.source_id is a foreign key, and a position only matches
    an id for as long as nobody reorders the file.

    feed_url is unique and the insert ignores conflicts, so this is idempotent
    and runs every hour without accumulating duplicates.
    """
    registered_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    client.insert_many(
        "sources",
        ("name", "feed_url", "homepage_url", "created_at"),
        [(s.name, s.feed_url, s.homepage_url, registered_at) for s in sources],
    )

    rows = client.query("SELECT id, feed_url FROM sources")
    return {row["feed_url"]: row["id"] for row in rows}


def fetch_drafts(
    sources=SOURCES,
    source_ids: dict[str, int] | None = None,
    now: datetime | None = None,
    get=None,
) -> list[ArticleDraft]:
    """Reads every feed. A portal that fails is skipped, not fatal."""
    now = now or datetime.now(UTC)
    get = get or _http_get
    source_ids = source_ids or {}

    drafts: list[ArticleDraft] = []
    for source in sources:
        source_id = source_ids.get(source.feed_url)
        if source_id is None:
            continue
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


def _article_ids(client: D1Client, urls: list[str]) -> dict[str, int]:
    """Maps URL to the id the corpus assigned, reading back in bounded chunks."""
    found: dict[str, int] = {}
    for start in range(0, len(urls), 100):
        window = urls[start : start + 100]
        placeholders = ", ".join("?" * len(window))
        rows = client.query(
            f"SELECT id, url FROM articles WHERE url IN ({placeholders})",
            window,
        )
        found.update({row["url"]: row["id"] for row in rows})
    return found


def _bump_document_counts(client: D1Client, counts: Counter) -> None:
    """Adds this run's document counts onto the corpus totals."""
    items = list(counts.items())
    rows_per_request = MAX_BOUND_PARAMS // 2

    for start in range(0, len(items), rows_per_request):
        chunk = items[start : start + rows_per_request]
        values = ", ".join(["(?, ?)"] * len(chunk))
        params = [value for pair in chunk for value in pair]
        client.query(
            f"INSERT INTO terms (term, doc_count) VALUES {values} "
            "ON CONFLICT(term) DO UPDATE SET doc_count = doc_count + excluded.doc_count",
            params,
        )


def store(client: D1Client, plan: IngestionPlan, now: datetime) -> None:
    """Writes a prepared plan to the corpus.

    Everything is batched. The first version issued four HTTP calls per
    article, which on the opening run meant roughly 1500 round trips from
    GitHub Actions to D1 and a job that timed out before finishing.

    Cluster ids are assigned here rather than read back from the database.
    Reading them back would mean either one round trip per insert or trusting
    the order RETURNING hands rows back in, which SQLite does not promise. The
    ingestion holds a concurrency lock, so nothing else is allocating ids.
    """
    if not plan.articles:
        return

    fetched_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    rows = client.query("SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM clusters")
    next_cluster_id = rows[0]["next_id"] if rows else 1

    cluster_rows = []
    article_rows = []
    for offset, article in enumerate(plan.articles):
        draft = article.draft
        cluster_id = assign_cluster(draft, article.term_frequencies, [])
        if cluster_id is None:
            cluster_id = next_cluster_id + offset
            cluster_rows.append((cluster_id, draft.published_at, 1))

        article_rows.append(
            (
                draft.source_id,
                cluster_id,
                draft.title,
                draft.summary,
                draft.url,
                draft.published_at,
                fetched_at,
            )
        )

    client.insert_many("clusters", ("id", "first_seen_at", "size"), cluster_rows)
    client.insert_many(
        "articles",
        ("source_id", "cluster_id", "title", "summary", "url", "published_at", "fetched_at"),
        article_rows,
    )

    ids = _article_ids(client, [a.draft.url for a in plan.articles])
    term_rows = [
        (ids[a.draft.url], term, tf)
        for a in plan.articles
        if a.draft.url in ids
        for term, tf in a.term_frequencies.items()
    ]
    client.insert_many("article_terms", ("article_id", "term", "tf"), term_rows)

    _bump_document_counts(client, plan.document_counts)

    client.query(
        "UPDATE corpus_stats SET total_docs = total_docs + ? WHERE id = 1",
        [plan.total_docs_delta],
    )


def run(client: D1Client | None = None, now: datetime | None = None) -> IngestionPlan:
    """One full pass: read the feeds, work out what is new, store it."""
    client = client or D1Client.from_env()
    now = now or datetime.now(UTC)

    source_ids = ensure_sources(client)
    drafts = fetch_drafts(SOURCES, source_ids, now=now)
    plan = prepare(drafts, known_urls(client, [d.url for d in drafts]))
    store(client, plan, now)
    return plan


if __name__ == "__main__":
    result = run()
    print(f"{result.total_docs_delta} artigos novos, {len(result.document_counts)} termos tocados")
