"""Tests for RSS parsing.

Only title, summary and link are kept, and the reader goes to the original
site. That respects the terms of the feeds and it is why the ingestion never
scrapes article bodies.
"""

from datetime import UTC, datetime

from ingest.feeds import (
    SUMMARY_MAX_CHARS,
    ArticleDraft,
    clean_summary,
    dedupe_by_url,
    parse_feed,
)

FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Portal de Teste</title>
    <item>
      <title>Copom mantem a Selic em 10,5% ao ano</title>
      <link>https://exemplo.com/copom-selic</link>
      <description>&lt;p&gt;O Comite   de Politica Monetaria decidiu&lt;/p&gt;</description>
      <pubDate>Wed, 29 Jul 2026 14:30:00 -0300</pubDate>
    </item>
    <item>
      <title>Sem data de publicacao</title>
      <link>https://exemplo.com/sem-data</link>
      <description>Resumo simples</description>
    </item>
    <item>
      <title>Item sem link nenhum</title>
      <description>Nao da para abrir</description>
    </item>
  </channel>
</rss>
"""

NOW = datetime(2026, 7, 31, 12, 0, 0, tzinfo=UTC)


class TestCleanSummary:
    def test_html_tags_are_stripped(self):
        assert clean_summary("<p>O Copom <b>manteve</b> a taxa</p>") == "O Copom manteve a taxa"

    def test_entities_are_decoded(self):
        assert clean_summary("Juros &amp; c&acirc;mbio") == "Juros & câmbio"

    def test_runs_of_whitespace_collapse(self):
        assert clean_summary("O Comite   de\n\n  Politica") == "O Comite de Politica"

    def test_empty_input_yields_empty_string(self):
        assert clean_summary("") == ""
        assert clean_summary(None) == ""

    def test_long_summaries_are_capped(self):
        """G1 and Agencia Brasil ship the whole article body in <description>.

        Measured against the live feeds: G1 averages 5690 characters and 243
        lemmas per item, Poder360 averages 125 characters and 15 lemmas. Term
        frequencies are normalized to sum to one, so uncapped, every G1 term
        would weigh 0.4% against a Poder360 term's 6.7%, and every G1 story
        would rank low for a reason that has nothing to do with the reader.

        It is the same class of invisible source bias the architecture rejects
        for dwell time, arriving from the opposite direction.
        """
        capped = clean_summary("palavra " * 400)

        assert len(capped) <= SUMMARY_MAX_CHARS

    def test_capping_does_not_cut_a_word_in_half(self):
        """The lemma of half a word is not a word, and the card shows it."""
        capped = clean_summary("antidisestablishmentarianism " * 40)

        assert not capped.endswith("antidis")
        assert capped.split()[-1] == "antidisestablishmentarianism"

    def test_a_short_summary_is_untouched(self):
        assert clean_summary("O Copom manteve a taxa") == "O Copom manteve a taxa"


class TestParseFeed:
    def test_extracts_title_url_and_summary(self):
        drafts = parse_feed(FEED, source_id=7, now=NOW)

        first = drafts[0]
        assert first.source_id == 7
        assert first.title == "Copom mantem a Selic em 10,5% ao ano"
        assert first.url == "https://exemplo.com/copom-selic"
        assert first.summary == "O Comite de Politica Monetaria decidiu"

    def test_publication_time_is_normalized_to_utc(self):
        """The feed says 14:30 at UTC-3, so the corpus stores 17:30 UTC.

        Ranking decays by age, so a story landing in the wrong timezone would
        be three hours too old or too fresh against every other source.
        """
        drafts = parse_feed(FEED, source_id=7, now=NOW)

        assert drafts[0].published_at == "2026-07-29T17:30:00Z"

    def test_missing_publication_time_falls_back_to_now(self):
        drafts = parse_feed(FEED, source_id=7, now=NOW)

        undated = next(d for d in drafts if d.url == "https://exemplo.com/sem-data")
        assert undated.published_at == "2026-07-31T12:00:00Z"

    def test_entries_without_a_link_are_dropped(self):
        """A card with nowhere to go is worse than no card."""
        drafts = parse_feed(FEED, source_id=7, now=NOW)

        assert all(d.url for d in drafts)
        assert "Item sem link nenhum" not in [d.title for d in drafts]

    def test_malformed_feed_yields_no_drafts_instead_of_raising(self):
        """One broken feed must not take the whole hourly run down with it."""
        assert parse_feed(b"isto nao e xml", source_id=1, now=NOW) == []


class TestDedupeByUrl:
    def test_first_occurrence_wins(self):
        a = ArticleDraft(1, "Primeiro", "resumo", "https://x.com/a", "2026-07-31T10:00:00Z")
        b = ArticleDraft(2, "Repetido", "outro", "https://x.com/a", "2026-07-31T11:00:00Z")
        c = ArticleDraft(1, "Outro", "resumo", "https://x.com/b", "2026-07-31T10:00:00Z")

        assert dedupe_by_url([a, b, c]) == [a, c]

    def test_empty_input_is_handled(self):
        assert dedupe_by_url([]) == []
