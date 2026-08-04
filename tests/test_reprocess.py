"""Tests for the pass that makes the stored corpus agree with today's rules.

What happens here and nowhere else is fixing text that was stored before a
cleaning rule existed. Arriving articles get both halves cleaned; the archive
only gets what this pass decides to rewrite.

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

        _, _, _, cleaned = run(client)

        assert cleaned == 1

    def test_the_cut_matches_what_arriving_articles_get(self):
        """One rule, reached from both sides. A second implementation here would
        drift from the one the ingestion uses and split the corpus by age.
        """
        assert "Clique aqui" not in strip_promotion(f"Chuva forte. {PROMO}")
