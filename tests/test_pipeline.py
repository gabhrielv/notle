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
        self.queries = []

    def query(self, sql, params=None):
        self.queries.append(sql)
        for fragment, rows in self.rows_by_sql.items():
            if fragment in sql:
                return rows
        return self.rows

    def insert_many(self, table, columns, rows):
        self.inserts.append((table, columns, list(rows)))
        self.queries.append(f"INSERT INTO {table}")


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


def draft(url: str, title: str, summary: str = "") -> ArticleDraft:
    return ArticleDraft(1, title, summary, url, "2026-07-31T12:00:00Z")


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
