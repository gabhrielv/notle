"""Tests for what the ingestion run decides to write.

The decision is separated from the writing on purpose: what gets stored has a
knowable right answer and is tested here, while the writing itself is a thin
layer over the D1 client that already has its own tests.
"""

from ingest.feeds import ArticleDraft
from ingest.pipeline import prepare


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
