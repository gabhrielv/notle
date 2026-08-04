"""Tests for the text normalization that feeds the whole ranking.

These are the functions with a knowable right answer, and they run against real
spaCy rather than a stand-in: a mock lemmatizer would only prove that the mock
returns what the test told it to.
"""

import pytest

from ingest.normalize import (
    SurfaceVotes,
    _nlp,
    canonical_map,
    canonize,
    lemmatize,
    occurrences,
    tally,
    term_frequencies,
)


class TestLemmatize:
    def test_inflected_forms_of_a_word_share_one_lemma(self):
        """The case that justifies lemmatizing instead of stemming.

        Untreated, `eleicoes` and `eleicao` become two terms that never meet,
        each carrying half the mass and an inflated IDF.
        """
        plural = lemmatize("As eleições municipais foram adiadas")
        singular = lemmatize("A eleição municipal foi adiada")

        assert "eleição" in plural
        assert "eleição" in singular

    def test_lemma_is_a_real_word_not_a_truncated_stem(self):
        """An aggressive stemmer would produce `eleic`.

        The screen shows this text to the user as the reason a story ranked
        where it did, so a stem would break the explainability the project
        exists for.
        """
        assert "eleição" in lemmatize("eleições")

    def test_stopwords_are_dropped(self):
        lemmas = lemmatize("O ministro de Estado falou com a imprensa")

        assert "de" not in lemmas
        assert "com" not in lemmas
        assert "o" not in lemmas

    def test_auxiliary_verbs_do_not_become_terms(self):
        """`ser` and `ter` carry no topic and would otherwise top every list."""
        lemmas = lemmatize("O presidente foi eleito e tem amplo apoio")

        assert "ser" not in lemmas
        assert "ter" not in lemmas

    def test_punctuation_is_dropped(self):
        lemmas = lemmatize("Selic: Copom mantém juros, diz ata.")

        assert ":" not in lemmas
        assert "," not in lemmas
        assert "." not in lemmas

    def test_case_is_normalized(self):
        assert lemmatize("INFLAÇÃO") == lemmatize("inflação")

    def test_empty_text_yields_no_lemmas(self):
        assert lemmatize("") == []

    def test_content_words_survive(self):
        """Guards against a filter so aggressive it empties the vector."""
        lemmas = lemmatize("Copom mantém a taxa Selic em 10,5% ao ano")

        assert "copom" in lemmas
        assert "selic" in lemmas

    def test_link_bait_boilerplate_is_not_a_term(self):
        """`Leia também` showed up in 129 of 311 real articles.

        It is navigation chrome the portal pastes into every summary, so it
        describes the template and not the story.
        """
        lemmas = lemmatize("Copom mantém a Selic. Leia também: o que muda no seu bolso")

        assert "leia" not in lemmas
        assert "ler" not in lemmas
        assert "selic" in lemmas

    def test_weekday_names_are_not_terms(self):
        """Nearly every article names a weekday, so it separates nothing."""
        lemmas = lemmatize("O Copom decidiu na quinta-feira manter a taxa")

        assert "quinta-feira" not in lemmas
        assert "copom" in lemmas

    def test_reporting_verbs_are_not_terms(self):
        """Same class as `dizer`: it marks attribution, not subject."""
        lemmas = lemmatize("O ministro afirmou que a meta de inflação será cumprida")

        assert "afirmar" not in lemmas
        assert "inflação" in lemmas

    def test_multiword_place_names_stay_together(self):
        """Split apart, the card would read: you follow `são`, `paulo`.

        Real feeds produced `são` 96 times and `paulo` 114 times as separate
        terms, which is two meaningless dimensions instead of one real one.
        """
        lemmas = lemmatize("O governo de São Paulo anunciou o novo plano")

        assert "são paulo" in lemmas
        assert "são" not in lemmas

    def test_contractions_are_not_expanded_inside_a_place_name(self):
        """Lemmatizing inside the span turns `do` into `de o`.

        Real feeds produced `rio grande de o sul`, which is not a phrase any
        reader would recognize as the state they live in.
        """
        lemmas = lemmatize("O governo do Rio Grande do Sul decretou emergência")

        assert "rio grande do sul" in lemmas
        assert "rio grande de o sul" not in lemmas

    def test_emoji_never_become_terms(self):
        """A portal prefixes summaries with an emoji, and it rode into a span."""
        lemmas = lemmatize("💲 Quanto custa a cesta básica em São Paulo")

        assert all("💲" not in lemma for lemma in lemmas)

    def test_a_headline_colon_is_a_boundary_not_part_of_a_name(self):
        """Entity recognition reads straight through the colon.

        The span came back as `Selic: Copom` and merged into one term that no
        other article could ever share, so the story stopped matching the same
        story from another portal. Against the three headlines the architecture
        uses as its example, this alone moved the cosine from 0.29 to 0.75, one
        side of the clustering threshold to the other.
        """
        lemmas = lemmatize("Selic: Copom mantém os juros em 10,5%")

        assert "selic" in lemmas
        assert "copom" in lemmas
        assert "selic: copom" not in lemmas

    def test_a_name_after_the_colon_still_merges(self):
        """Splitting must not cost what merging was for.

        The segment on each side of the punctuation is still offered to the
        merge, so a multi-word name keeps its single term.
        """
        lemmas = lemmatize("Acústico: Charlie Brown Jr faz show no Rio de Janeiro")

        assert "charlie brown jr" in lemmas
        assert "rio de janeiro" in lemmas
        assert "acústico" in lemmas


class TestEnglish:
    """The technology feeds publish in English, and the model has to follow."""

    def test_the_portuguese_model_invents_words_in_english(self):
        """Why a second model rather than one that does its best.

        Running Portuguese over English does not merely lose quality, it makes
        up lemmas: `build` comes back as `buildr`, `tighten` as `tightem`.
        Terms the reader is shown as the reason a story ranked cannot be words
        that do not exist.
        """
        wrong = lemmatize("rivals race to build cheaper models as supply tightens", "pt")

        assert "buildr" in wrong
        assert "build" not in wrong

    def test_plurals_collapse_the_way_they_have_to(self):
        """The same failure the Portuguese side exists to prevent, in English.

        Untreated, `model` and `models` are two terms that never meet, each
        holding half the mass with an inflated IDF.
        """
        singular = lemmatize("the model shipped", "en")
        plural = lemmatize("the models shipped", "en")

        assert "model" in singular
        assert "model" in plural

    def test_attribution_is_dropped_in_english_too(self):
        """`sources say` names who spoke, never what happened, exactly as
        `afirmar` did in Portuguese.
        """
        lemmas = lemmatize("Apple delays the hub, sources say", "en")

        assert "say" not in lemmas
        assert "delay" in lemmas

    def test_an_unknown_language_falls_back_rather_than_failing(self):
        """A feed added with a typo in its language must degrade, not take the
        hourly run down with it.
        """
        assert lemmatize("Copom mantém a Selic", "xx") == lemmatize("Copom mantém a Selic")

    def test_each_language_keeps_its_own_model_loaded(self):
        """The cache is keyed by language, so a run that alternates between
        Portuguese and English feeds does not reload a model per article.
        """
        lemmatize("teste", "pt")
        lemmatize("test", "en")

        assert _nlp("pt") is not _nlp("en")
        assert _nlp("pt") is _nlp("pt")


class TestTermFrequencies:
    def test_frequencies_sum_to_one(self):
        tf = term_frequencies(["juros", "selic", "juros", "copom"])

        assert sum(tf.values()) == pytest.approx(1.0)

    def test_frequency_is_proportional_to_count(self):
        tf = term_frequencies(["juros", "selic", "juros", "copom"])

        assert tf["juros"] == pytest.approx(0.5)
        assert tf["selic"] == pytest.approx(0.25)
        assert tf["copom"] == pytest.approx(0.25)

    def test_empty_input_yields_empty_vector(self):
        """A headline that normalizes to nothing must not divide by zero."""
        assert term_frequencies([]) == {}


class TestOccurrences:
    def test_the_first_word_of_the_text_opens_a_sentence(self):
        found = occurrences("Petrobras anuncia lucro recorde")

        assert found[0].opens_sentence
        assert not any(other.opens_sentence for other in found[1:])

    def test_the_word_after_a_full_stop_opens_a_sentence(self):
        """The parser is disabled, so spaCy segments nothing and marks only the
        very first token. The pipeline hands this function `title. summary`, so
        the word this misses would be the first word of every summary.
        """
        found = occurrences("Lucro recorde. Equipes celebram o resultado")
        opening = [x.surface for x in found if x.opens_sentence]

        assert opening == ["lucro", "equipes"]

    def test_a_comma_does_not_open_a_sentence(self):
        found = occurrences("Recife registrou chuva, equipes de resgate chegaram")

        assert [x.surface for x in found if x.opens_sentence] == ["recife"]

    def test_a_word_the_article_precedes_is_not_at_an_opening(self):
        """`A Petrobras anunciou` reads correctly precisely because the article
        takes the opening and the name sits inside the sentence. The flag has to
        be spent by the determiner even though the determiner is discarded.
        """
        found = occurrences("A Petrobras anunciou lucro")

        assert not any(x.opens_sentence for x in found)

    def test_surface_is_lowercased_so_position_does_not_split_the_key(self):
        """The capital is the accident being corrected for, so the word opening
        a headline has to land in the same bucket as the same word inside one.
        """
        opening = occurrences("Equipes de resgate chegaram")
        inside = occurrences("As equipes de resgate chegaram")

        assert opening[0].surface == "equipes"
        assert [x for x in inside if x.surface == "equipes"]

    def test_lemmatize_returns_the_same_lemmas_as_before(self):
        assert lemmatize("As eleições municipais foram adiadas") == [
            found.lemma for found in occurrences("As eleições municipais foram adiadas")
        ]


class TestCanonicalMap:
    def poll(self, *texts, language="pt"):
        votes: dict[str, SurfaceVotes] = {}
        for text in texts:
            tally(votes, occurrences(text, language))
        return votes

    def test_only_readings_taken_mid_sentence_vote(self):
        """Letting the opening vote would be asking the error to confirm itself."""
        votes = self.poll("Equipes de resgate chegaram ao local")

        assert "equipes" not in votes

    def test_a_written_word_needs_more_than_one_reading_to_decide(self):
        """`chance` came back as `chancer` on its single settled occurrence in
        the headline corpus. One observation electing a canonical form unopposed
        is how a common word acquires an invented lemma.
        """
        once = self.poll("Houve uma chance real")

        assert canonical_map(once) == {}

    def test_a_word_only_ever_seen_opening_a_sentence_gets_no_entry(self):
        votes = self.poll(*["Equipes chegaram" for _ in range(5)])

        assert "equipes" not in canonical_map(votes)

    def test_different_written_words_never_merge(self):
        """The protection that a rule matching `X` against `Xs` has to work for,
        and that three variants against entity recognition failed to get. `deu`
        and `deus` are separate strings on the page, so no count can bring them
        together.
        """
        votes = self.poll(
            "Ele deu a resposta certa",
            "Ela deu o troco exato",
            "O juiz deu a sentença",
            "A fé em Deus move o grupo",
            "O templo de Deus foi restaurado",
            "A palavra de Deus foi lida",
        )
        canonical = canonical_map(votes)

        assert canonical.get("deus") != canonical.get("deu")
        assert canonical.get("deus") not in {"dar", "deu"}

    def test_nothing_mid_sentence_is_ever_rewritten(self):
        """A wrong entry can reach only the openings of one written word, never
        every occurrence of a term.
        """
        found = occurrences("As equipes de resgate chegaram")
        lemmas = canonize(found, {"equipes": "coisa-nenhuma"})

        assert "coisa-nenhuma" not in lemmas

    def test_an_opening_is_held_to_what_the_corpus_settled_on(self):
        found = occurrences("Equipes de resgate chegaram")
        lemmas = canonize(found, {"equipes": "equipe"})

        assert "equipe" in lemmas
        assert "equipes" not in lemmas

    def test_an_empty_map_leaves_every_lemma_alone(self):
        """The state before the reprocessing has ever run."""
        found = occurrences("Equipes de resgate chegaram")

        assert canonize(found, {}) == [x.lemma for x in found]
