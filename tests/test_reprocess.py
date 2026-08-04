"""Tests for the pass that makes the stored corpus agree with today's rules.

Two things happen here that happen nowhere else, and both are why the job reads
the whole archive rather than one batch. It counts the canonical vote, which is a
tally over every occurrence in the corpus, and it fixes text that was stored
before a cleaning rule existed.

The D1 client is faked. What is worth testing is which statements the pass
decides to run and what it binds to them, and a real database would only add a
credential to the loop.
"""

from ingest.feeds import strip_promotion
from scripts.reprocess_terms import run
from tests.test_pipeline import FakeClient

PROMO = "Clique aqui para seguir o canal do g1 Recife no WhatsApp"


class Corpus(FakeClient):
    """Replays one page of articles and then the end of the archive.

    `read_articles` pages with LIMIT and OFFSET until it gets nothing back, so a
    fake that answered the same rows forever would never let the pass finish.
    """

    def __init__(self, articles):
        super().__init__()
        self.articles = articles
        self.pages = 0

    def query(self, sql, params=None):
        self.calls.append((sql, list(params or [])))
        if "FROM articles a JOIN sources s" in sql:
            self.pages += 1
            return self.articles if self.pages == 1 else []
        return []


def article(article_id: int, title: str, summary: str = "") -> dict:
    return {
        "id": article_id,
        "title": title,
        "summary": summary,
        "feed_url": "https://g1.globo.com/rss/g1/",
    }


class TestPromotionInStoredText:
    def test_the_invitation_is_cut_from_the_stored_title(self):
        """Arriving articles have had both halves cleaned since the rule
        existed, because `clean_summary` runs over the title too. This job only
        ever rewrote the summary and then lemmatized the stored title raw, so
        the title was the one place still carrying the invitation into the
        corpus that gets measured.
        """
        client = Corpus([article(1, f"Chuva forte no Recife. {PROMO}", "Resumo limpo")])

        run(client)

        written = client.params_matching("UPDATE articles SET title")
        assert written, "o titulo armazenado nunca foi reescrito"
        assert "Clique aqui" not in written[0][0]

    def test_the_search_index_moves_with_the_visible_text(self):
        """`article_search` is a plain FTS5 table with its own copy. Left
        behind, a query for the invitation returns articles whose visible text
        no longer contains it.
        """
        client = Corpus([article(1, f"Chuva forte. {PROMO}", f"Resumo. {PROMO}")])

        run(client)

        assert client.params_matching("UPDATE article_search SET title")

    def test_text_that_never_carried_it_is_not_rewritten(self):
        client = Corpus([article(1, "Copom mantem a Selic", "O comite decidiu manter")])

        run(client)

        assert not client.params_matching("UPDATE articles SET title")

    def test_the_count_reports_what_was_cleaned(self):
        client = Corpus(
            [
                article(1, f"Chuva forte. {PROMO}", "Resumo"),
                article(2, "Copom mantem a Selic", "O comite decidiu"),
            ]
        )

        _, _, _, cleaned, _ = run(client)

        assert cleaned == 1

    def test_the_cut_matches_what_arriving_articles_get(self):
        """One rule, reached from both sides. A second implementation here would
        drift from the one the ingestion uses and split the corpus by age.
        """
        assert "Clique aqui" not in strip_promotion(f"Chuva forte. {PROMO}")


class TestCanonicalVote:
    def test_the_vote_is_written_for_the_ingestion_to_read(self):
        """The hourly pass cannot count this itself: it sees one batch, and the
        tally is over the corpus. Without the table it would write the same
        split terms this job just merged.
        """
        client = Corpus(
            [
                article(i, "Chuva no Recife", "As equipes de resgate chegaram ao local")
                for i in range(1, 6)
            ]
        )

        run(client)

        assert client.rows_written("term_canonical")

    def test_the_map_is_replaced_rather_than_merged(self):
        """A written word that lost its evidence since the last run should lose
        its entry, and reconciling that costs a read to save batched writes.
        """
        client = Corpus([article(1, "Copom mantem a Selic", "O comite decidiu")])

        run(client)

        assert any("DELETE FROM term_canonical" in sql for sql in client.queries)

    def test_a_dry_run_writes_nothing(self):
        client = Corpus([article(1, f"Chuva. {PROMO}", "As equipes chegaram ao local")])

        run(client, dry_run=True)

        assert not client.inserts
        assert not any(
            sql.startswith(("UPDATE", "DELETE")) for sql in client.queries
        )

    def test_the_ingestion_survives_a_table_that_does_not_exist_yet(self):
        """Migrations are applied by the deploy workflow and the ingestion runs
        twice an hour on its own, so there is a window where the code knows
        about a table the database has not been given. Stopping for it would
        trade a corpus that splits terms for no corpus at all.
        """
        from ingest.pipeline import canonical_forms
        from ingest.store import D1Error

        class Missing:
            def query(self, sql, params=None):
                raise D1Error("no such table: term_canonical")

        assert canonical_forms(Missing()) == {}

    def test_the_model_runs_once_over_the_archive(self):
        """The vote has to be complete before any article can be canonized, and
        re-reading the corpus to get there would double the expensive half of
        the job. The readings are held between the two passes instead.
        """
        client = Corpus([article(i, "Chuva no Recife", "O resumo") for i in range(1, 4)])

        run(client)

        assert client.pages == 2, "o acervo foi lido mais de uma vez"
