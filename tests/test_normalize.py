"""Tests for the text normalization that feeds the whole ranking.

These are the functions with a knowable right answer, and they run against real
spaCy rather than a stand-in: a mock lemmatizer would only prove that the mock
returns what the test told it to.
"""

import pytest

from ingest.normalize import lemmatize, term_frequencies


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
