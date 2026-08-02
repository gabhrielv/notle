"""Orchestrates one ingestion run.

The decision of what to store is a pure function over the drafts and the URLs
already in the corpus. The writing is a thin layer on top. Keeping them apart
is what lets the part with a knowable right answer be tested without a network
or a credential.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx

from ingest import candidates
from ingest.clustering import assign_cluster
from ingest.feeds import ArticleDraft, dedupe_by_url, parse_feed
from ingest.normalize import lemmatize, term_frequencies
from ingest.sources import SOURCES
from ingest.store import MAX_BOUND_PARAMS, D1Client, chunked
from ranking.vectors import weigh

USER_AGENT = "notle/0.1 (+https://github.com/gabhrielv/notle)"
FETCH_TIMEOUT = 25.0

# How far back a story can still gather later coverage. A day is roughly how
# long the same event keeps being republished; past that, an article about the
# same subject is a follow up rather than the same story, and it deserves its
# own card.
CLUSTER_WINDOW_HOURS = 24


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


def corpus_size(client: D1Client) -> int:
    """How many documents the IDF is measured against."""
    rows = client.query("SELECT total_docs FROM corpus_stats WHERE id = 1")
    return rows[0]["total_docs"] if rows else 0


def document_counts(client: D1Client, terms: set[str]) -> dict[str, int]:
    """Reads doc_count for the terms this run actually compares.

    Selecting the whole table would be one request instead of a few dozen, and
    that is the cheaper trade only while the corpus is small. `terms` grows with
    the vocabulary and never shrinks, while a single run touches a few thousand
    of them, so reading everything would eventually mean scanning six figures of
    rows every hour for an answer of constant size.

    The counts are whatever the corpus holds when this is called, which is the
    reason both callers are explicit about when they call it.
    """
    counts: dict[str, int] = {}
    for chunk in chunked(sorted(terms), MAX_BOUND_PARAMS):
        placeholders = ", ".join("?" * len(chunk))
        rows = client.query(
            f"SELECT term, doc_count FROM terms WHERE term IN ({placeholders})",
            chunk,
        )
        counts.update({row["term"]: row["doc_count"] for row in rows})
    return counts


def recent_anchors(client: D1Client, now: datetime) -> list[tuple[int, dict[str, float]]]:
    """The raw term frequencies of the article that opened each recent cluster.

    A cluster whose representative is still unset is left out rather than
    matched against nothing. That is the safe direction: if a run dies between
    inserting the articles and pointing the clusters at them, the worst the next
    run can do is open a second cluster for a story, never merge two stories
    that do not belong together.
    """
    since = (now - timedelta(hours=CLUSTER_WINDOW_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = client.query(
        "SELECT c.id AS cluster_id, t.term, t.tf "
        "FROM clusters c "
        "JOIN article_terms t ON t.article_id = c.representative_article_id "
        "WHERE c.first_seen_at >= ? AND c.representative_article_id IS NOT NULL",
        [since],
    )

    anchors: dict[int, dict[str, float]] = defaultdict(dict)
    for row in rows:
        anchors[row["cluster_id"]][row["term"]] = row["tf"]
    return list(anchors.items())


def set_representatives(client: D1Client, representatives: dict[int, int]) -> None:
    """Points each cluster opened in this run at the article that opened it.

    The article id only exists after its insert, so this cannot ride along with
    the cluster row and has to be a second pass. One statement per cluster would
    be hundreds of round trips, so the assignments travel as a CASE.
    """
    if not representatives:
        return

    # Three bound parameters per cluster: the id twice in the CASE, once in the
    # IN. Without the IN, every other cluster in the table would match the
    # UPDATE and have its representative set to NULL by the CASE falling through.
    for chunk in chunked(list(representatives.items()), MAX_BOUND_PARAMS // 3):
        cases = " ".join(["WHEN ? THEN ?"] * len(chunk))
        placeholders = ", ".join("?" * len(chunk))
        params = [value for pair in chunk for value in pair] + [cid for cid, _ in chunk]
        client.query(
            f"UPDATE clusters SET representative_article_id = CASE id {cases} END "
            f"WHERE id IN ({placeholders})",
            params,
        )


def _grow_clusters(client: D1Client, growth: Counter) -> None:
    """Adds this run's new members onto the size of clusters that already existed.

    Grouped by how many members each gained, so the number of requests follows
    the distinct increments, which is almost always one or two, instead of the
    number of clusters touched.
    """
    by_increment: dict[int, list[int]] = defaultdict(list)
    for cluster_id, gained in growth.items():
        by_increment[gained].append(cluster_id)

    for gained, cluster_ids in by_increment.items():
        for chunk in chunked(cluster_ids, MAX_BOUND_PARAMS - 1):
            placeholders = ", ".join("?" * len(chunk))
            client.query(
                f"UPDATE clusters SET size = size + ? WHERE id IN ({placeholders})",
                [gained, *chunk],
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

    # Read before anything is written, so the IDF holds still for the whole
    # pass. If it moved as the batch was processed, which articles grouped with
    # which would depend on the order the feeds happened to answer in.
    anchors = recent_anchors(client, now)
    total_docs = corpus_size(client)
    counts = document_counts(
        client,
        {term for article in plan.articles for term in article.term_frequencies}
        | {term for _, anchor in anchors for term in anchor},
    )
    candidates = [(cluster_id, weigh(anchor, counts, total_docs)) for cluster_id, anchor in anchors]

    rows = client.query("SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM clusters")
    next_cluster_id = rows[0]["next_id"] if rows else 1

    # Oldest first, so the portal that broke the story opens the cluster and the
    # rewrites attach to it. Feed order would hand the anchor to whichever
    # portal happened to be read first.
    arriving = sorted(plan.articles, key=lambda article: article.draft.published_at)

    opened: dict[int, tuple[str, str]] = {}
    members: Counter = Counter()
    article_rows = []
    for article in arriving:
        draft = article.draft
        vector = weigh(article.term_frequencies, counts, total_docs)
        cluster_id = assign_cluster(vector, candidates)

        if cluster_id is None:
            cluster_id = next_cluster_id
            next_cluster_id += 1
            opened[cluster_id] = (draft.published_at, draft.url)
            # A cluster opened in this run has to be able to catch the rewrites
            # that arrive later in the same run. Three portals covering one
            # event usually land in a single hourly read.
            candidates.append((cluster_id, vector))

        members[cluster_id] += 1
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

    cluster_rows = [
        (cluster_id, first_seen_at, members[cluster_id])
        for cluster_id, (first_seen_at, _) in opened.items()
    ]
    grown = Counter(
        {cluster_id: gained for cluster_id, gained in members.items() if cluster_id not in opened}
    )

    client.insert_many("clusters", ("id", "first_seen_at", "size"), cluster_rows)
    client.insert_many(
        "articles",
        ("source_id", "cluster_id", "title", "summary", "url", "published_at", "fetched_at"),
        article_rows,
    )

    ids = _article_ids(client, [a.draft.url for a in plan.articles])

    set_representatives(
        client,
        {cluster_id: ids[url] for cluster_id, (_, url) in opened.items() if url in ids},
    )
    _grow_clusters(client, grown)

    term_rows = [
        (ids[a.draft.url], term, tf)
        for a in plan.articles
        if a.draft.url in ids
        for term, tf in a.term_frequencies.items()
    ]
    client.insert_many("article_terms", ("article_id", "term", "tf"), term_rows)

    # The search index gets the text as the portal wrote it, not the lemmas.
    # Someone typing into a search box is not writing lemmas, and FTS5 folds the
    # diacritics on both sides, so `eleicao` finds `eleição` without the query
    # ever having to pass through a model the Worker cannot load.
    search_rows = [
        (ids[a.draft.url], a.draft.title, a.draft.summary)
        for a in plan.articles
        if a.draft.url in ids
    ]
    client.insert_many("article_search", ("rowid", "title", "summary"), search_rows)

    _bump_document_counts(client, plan.document_counts)

    client.query(
        "UPDATE corpus_stats SET total_docs = total_docs + ? WHERE id = 1",
        [plan.total_docs_delta],
    )


def refresh_candidates(client: D1Client, now: datetime) -> int:
    """Rebuilds the table the feed reads, after this run's writes have landed.

    It runs last on purpose. The document counts it weighs with are the ones
    including everything this run just stored, so the window a request will read
    is measured against the corpus that actually exists rather than the one that
    existed an hour ago.
    """
    rows = candidates.read_window(client, now)
    if not rows:
        return 0

    total_docs = corpus_size(client)
    counts = document_counts(client, {row["term"] for row in rows})

    built = candidates.build(rows, counts, total_docs, now)
    candidates.materialize(client, built)
    return len(built)


def run(client: D1Client | None = None, now: datetime | None = None) -> tuple[IngestionPlan, int]:
    """One full pass: read the feeds, work out what is new, store it, publish it."""
    client = client or D1Client.from_env()
    now = now or datetime.now(UTC)

    source_ids = ensure_sources(client)
    drafts = fetch_drafts(SOURCES, source_ids, now=now)
    plan = prepare(drafts, known_urls(client, [d.url for d in drafts]))
    store(client, plan, now)
    published = refresh_candidates(client, now)

    return plan, published


if __name__ == "__main__":
    result, published = run()
    print(
        f"{result.total_docs_delta} artigos novos, "
        f"{len(result.document_counts)} termos tocados, "
        f"{published} clusters no feed"
    )
