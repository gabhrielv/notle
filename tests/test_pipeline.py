"""Tests for what the ingestion run decides to write.

The decision is separated from the writing on purpose: what gets stored has a
knowable right answer and is tested here, while the writing itself is a thin
layer over the D1 client that already has its own tests.
"""

from datetime import UTC, datetime

from ingest.feeds import ArticleDraft
from ingest.pipeline import ensure_sources, fetch_drafts, prepare, store
from ingest.sources import Source

FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><item>
  <title>Copom mantem a Selic</title>
  <link>https://exemplo.com/copom</link>
  <description>Resumo</description>
</item></channel></rss>
"""


class FakeClient:
    """Records writes and replays canned reads."""

    def __init__(self, rows=None, rows_by_sql=None):
        self.rows = rows or []
        self.rows_by_sql = rows_by_sql or {}
        self.inserts = []
        self.calls = []

    @property
    def queries(self):
        return [sql for sql, _ in self.calls]

    def query(self, sql, params=None):
        self.calls.append((sql, list(params or [])))
        for fragment, rows in self.rows_by_sql.items():
            if fragment in sql:
                return rows
        return self.rows

    def insert_many(self, table, columns, rows):
        self.inserts.append((table, columns, list(rows)))
        self.calls.append((f"INSERT INTO {table}", list(rows)))

    def rows_written(self, table):
        """The rows handed to insert_many for one table."""
        return [row for name, _, rows in self.inserts if name == table for row in rows]

    def params_matching(self, fragment):
        """The bound parameters of every statement whose SQL contains `fragment`."""
        return [params for sql, params in self.calls if fragment in sql]


class TestEnsureSources:
    def test_returns_the_id_the_database_gave_each_feed(self):
        """articles.source_id is a foreign key.

        Using a feed's position in the tuple as its id assumes the database
        agrees with the order of a source file, and the first real run failed
        the constraint because nothing had registered the sources at all.
        """
        client = FakeClient(rows=[{"id": 9, "feed_url": "https://a/rss"}])

        ids = ensure_sources(client, (Source("A", "https://a/rss", "https://a"),))

        assert ids == {"https://a/rss": 9}

    def test_registers_every_configured_feed(self):
        client = FakeClient(rows=[])
        sources = (
            Source("A", "https://a/rss", "https://a"),
            Source("B", "https://b/rss", "https://b"),
        )

        ensure_sources(client, sources)

        table, _, rows = client.inserts[0]
        assert table == "sources"
        assert len(rows) == 2


class TestFetchDrafts:
    def test_drafts_carry_the_registered_id_not_the_list_position(self):
        sources = (Source("A", "https://a/rss", "https://a"),)

        drafts = fetch_drafts(sources, {"https://a/rss": 42}, get=lambda url: FEED)

        assert drafts[0].source_id == 42

    def test_a_feed_that_fails_is_skipped_not_fatal(self):
        def explode(url):
            raise TimeoutError("portal fora do ar")

        sources = (Source("A", "https://a/rss", "https://a"),)

        assert fetch_drafts(sources, {"https://a/rss": 1}, get=explode) == []


def draft(
    url: str,
    title: str,
    summary: str = "",
    published_at: str = "2026-07-31T12:00:00Z",
    source_id: int = 1,
) -> ArticleDraft:
    return ArticleDraft(source_id, title, summary, url, published_at)


class TestPrepare:
    def test_articles_already_in_the_corpus_are_skipped(self):
        """The hourly run re-reads feeds that mostly have not changed.

        G1 alone serves 100 items every hour, and almost all of them were
        already read last hour.
        """
        drafts = [
            draft("https://x.com/velho", "Copom mantém a Selic"),
            draft("https://x.com/novo", "Inflação desacelera em julho"),
        ]

        plan = prepare(drafts, known_urls={"https://x.com/velho"})

        assert [a.draft.url for a in plan.articles] == ["https://x.com/novo"]

    def test_document_count_rises_once_per_document_not_per_occurrence(self):
        """The classic IDF bug.

        `log(total_docs / doc_count)` only means anything if doc_count counts
        documents. Counting occurrences would let one article that repeats a
        term ten times push that term's IDF toward zero for everyone.

        The repetitions are spread across the sentence rather than adjacent:
        three of the same proper noun in a row is text no portal publishes, and
        entity recognition rightly reads it as one long name.
        """
        drafts = [
            draft(
                "https://x.com/a",
                "Selic sobe e a Selic fecha o ano com a Selic em alta",
            )
        ]

        plan = prepare(drafts, known_urls=set())

        assert plan.document_counts["selic"] == 1

    def test_a_term_in_two_articles_counts_twice(self):
        drafts = [
            draft("https://x.com/a", "Copom decide sobre a Selic"),
            draft("https://x.com/b", "Selic fecha o ano em alta"),
        ]

        plan = prepare(drafts, known_urls=set())

        assert plan.document_counts["selic"] == 2

    def test_each_article_carries_its_own_frequencies(self):
        drafts = [draft("https://x.com/a", "Inflação e juros no Brasil")]

        plan = prepare(drafts, known_urls=set())

        frequencies = plan.articles[0].term_frequencies
        assert sum(frequencies.values()) > 0.99
        assert "inflação" in frequencies

    def test_the_corpus_grows_by_the_number_of_new_articles(self):
        drafts = [
            draft("https://x.com/a", "Primeira matéria sobre juros"),
            draft("https://x.com/b", "Segunda matéria sobre câmbio"),
            draft("https://x.com/velha", "Ja conhecida"),
        ]

        plan = prepare(drafts, known_urls={"https://x.com/velha"})

        assert plan.total_docs_delta == 2

    def test_an_article_that_normalizes_to_nothing_is_dropped(self):
        """An empty vector has cosine zero against every profile forever.

        Storing it costs a row and a cluster that can never rank.
        """
        drafts = [draft("https://x.com/vazio", "...", "")]

        plan = prepare(drafts, known_urls=set())

        assert plan.articles == []

    def test_nothing_new_yields_an_empty_plan(self):
        plan = prepare([], known_urls=set())

        assert plan.articles == []
        assert plan.total_docs_delta == 0


class TestStore:
    def test_round_trips_do_not_scale_with_the_number_of_articles(self):
        """Every request here is an HTTP call from GitHub Actions to D1.

        The first version issued four per article, which meant roughly 1500
        calls on the opening run and a job that timed out before finishing.
        Writing is batched, so twenty articles must not cost eighty calls.
        """
        drafts = [draft(f"https://x.com/{i}", f"Materia {i} sobre juros") for i in range(20)]
        plan = prepare(drafts, known_urls=set())

        client = FakeClient(
            rows_by_sql={
                "MAX(id)": [{"next_id": 1}],
                "SELECT id, url FROM articles": [
                    {"id": i, "url": f"https://x.com/{i}"} for i in range(20)
                ],
            }
        )
        store(client, plan, datetime(2026, 7, 31, tzinfo=UTC))

        assert len(client.queries) < 20

    def test_nothing_new_writes_nothing(self):
        client = FakeClient()

        store(client, prepare([], known_urls=set()), datetime(2026, 7, 31, tzinfo=UTC))

        assert client.queries == []


NOW = datetime(2026, 7, 31, 12, tzinfo=UTC)

# The three headlines the architecture uses to state the problem, as the portals
# actually write them.
COPOM = [
    draft(
        "https://g1/copom",
        "Copom mantém a Selic em 10,5% ao ano",
        published_at="2026-07-31T09:00:00Z",
        source_id=1,
    ),
    draft(
        "https://bbc/selic",
        "Banco Central decide manter a taxa Selic em 10,5%",
        published_at="2026-07-31T09:20:00Z",
        source_id=2,
    ),
    draft(
        "https://cnn/juros",
        "Selic: Copom mantém os juros em 10,5%",
        published_at="2026-07-31T09:40:00Z",
        source_id=3,
    ),
]


def clustering_client(drafts, anchors=(), next_cluster_id=100, total_docs=311):
    """A client canned for the reads `store` makes on the way to clustering.

    `terms` comes back empty, so every term gets the same IDF and the cosine
    falls back to comparing raw frequencies. That keeps these tests about the
    grouping rather than about which words the corpus happens to consider rare;
    the weighting itself is covered in test_clustering.py.
    """
    return FakeClient(
        rows_by_sql={
            "total_docs FROM corpus_stats": [{"total_docs": total_docs}],
            "FROM terms WHERE term IN": [],
            "JOIN article_terms": list(anchors),
            "MAX(id)": [{"next_id": next_cluster_id}],
            "SELECT id, url FROM articles": [
                {"id": 500 + i, "url": d.url} for i, d in enumerate(drafts)
            ],
        }
    )


def cluster_of(client, url):
    """The cluster id the article with this URL was written under."""
    for row in client.rows_written("articles"):
        if row[4] == url:
            return row[1]
    raise AssertionError(f"{url} was never written")


class TestStoreClustering:
    def test_three_portals_covering_one_event_share_a_cluster(self):
        """The whole point of the slice.

        Ungrouped, these three take the top of the feed with tied scores, and a
        like on one pushes the other two up with it.
        """
        plan = prepare(COPOM, known_urls=set())
        client = clustering_client(COPOM)

        store(client, plan, NOW)

        assert len({cluster_of(client, d.url) for d in COPOM}) == 1

    def test_a_cluster_opened_this_run_catches_the_rest_of_the_run(self):
        """Three portals covering one event usually land in a single hourly read.

        Only the first of them can match against the database, because the other
        two are in the same batch. If the candidate list did not grow as the
        batch was processed, dedup would only ever work across runs.
        """
        plan = prepare(COPOM, known_urls=set())
        client = clustering_client(COPOM, anchors=[])

        store(client, plan, NOW)

        assert len(client.rows_written("clusters")) == 1

    def test_the_earliest_article_opens_the_cluster(self):
        """Feed order would hand the anchor to whichever portal was read first.

        The drafts are deliberately passed newest first here, so publication
        order is the only thing that can produce the expected answer.
        """
        reversed_order = list(reversed(COPOM))
        plan = prepare(reversed_order, known_urls=set())
        client = clustering_client(reversed_order)

        store(client, plan, NOW)

        first_seen_at = client.rows_written("clusters")[0][1]
        assert first_seen_at == "2026-07-31T09:00:00Z"

    def test_the_cluster_points_at_the_article_that_opened_it(self):
        """The anchor is what every later article is matched against.

        A cluster left pointing at nothing is invisible to the window query and
        silently stops gathering coverage, so the assignment is not optional.
        `clustering_client` hands out ids from 500 in the order it is given, and
        the G1 story is the oldest of the three.
        """
        plan = prepare(COPOM, known_urls=set())
        client = clustering_client(COPOM)

        store(client, plan, NOW)

        g1_article_id = 500
        assignments = client.params_matching("UPDATE clusters SET representative_article_id")
        assert assignments == [[100, g1_article_id, 100]]

    def test_a_new_cluster_is_sized_by_what_this_run_put_in_it(self):
        plan = prepare(COPOM, known_urls=set())
        client = clustering_client(COPOM)

        store(client, plan, NOW)

        _, _, size = client.rows_written("clusters")[0]
        assert size == 3

    def test_an_unrelated_story_opens_its_own_cluster(self):
        drafts = [
            *COPOM,
            draft(
                "https://g1/futebol",
                "Grêmio perde para o Bolívar e é eliminado da Copa Sul-Americana",
                published_at="2026-07-31T10:00:00Z",
            ),
        ]
        plan = prepare(drafts, known_urls=set())
        client = clustering_client(drafts)

        store(client, plan, NOW)

        assert len(client.rows_written("clusters")) == 2
        assert cluster_of(client, "https://g1/futebol") != cluster_of(client, "https://g1/copom")

    def test_an_article_joins_a_cluster_an_earlier_run_opened(self):
        """A story keeps being republished for hours after it breaks.

        The rewrite that arrives next hour has to find the cluster from last
        hour, not start a second one for the same event.
        """
        latecomer = [
            draft(
                "https://folha/selic",
                "Copom mantém a Selic em 10,5% ao ano, decide Banco Central",
                published_at="2026-07-31T11:00:00Z",
                source_id=4,
            )
        ]
        anchors = [
            {"cluster_id": 42, "term": term, "tf": tf}
            for term, tf in {"copom": 0.25, "manter": 0.25, "selic": 0.25, "ano": 0.25}.items()
        ]
        plan = prepare(latecomer, known_urls=set())
        client = clustering_client(latecomer, anchors=anchors)

        store(client, plan, NOW)

        assert client.rows_written("clusters") == []
        assert cluster_of(client, "https://folha/selic") == 42

    def test_joining_an_existing_cluster_grows_its_size(self):
        anchors = [
            {"cluster_id": 42, "term": term, "tf": tf}
            for term, tf in {"copom": 0.25, "manter": 0.25, "selic": 0.25, "ano": 0.25}.items()
        ]
        plan = prepare(COPOM, known_urls=set())
        client = clustering_client(COPOM, anchors=anchors)

        store(client, plan, NOW)

        growth = client.params_matching("SET size = size +")
        assert growth == [[3, 42]]

    def test_the_window_asks_for_one_day(self):
        plan = prepare(COPOM, known_urls=set())
        client = clustering_client(COPOM)

        store(client, plan, NOW)

        assert client.params_matching("JOIN article_terms") == [["2026-07-30T12:00:00Z"]]
