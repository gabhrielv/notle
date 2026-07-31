"""Turns headline text into the terms that carry topic.

Lemmas, not stems. Portuguese is heavily inflected, so without treatment
`eleicoes` and `eleicao` become two terms that never meet, each holding half the
mass with an inflated IDF. An aggressive stemmer would match them at the cost of
producing `eleic`, and the screen shows this text to the user as the reason a
story ranked where it did.
"""

import functools
from collections import Counter

import spacy

MODEL = "pt_core_news_sm"

# The parts of speech that carry topic. Everything else (determiner,
# preposition, conjunction, pronoun, auxiliary, numeral, symbol, punctuation)
# is structure, and structure is the same in every article.
CONTENT_POS = frozenset({"NOUN", "PROPN", "ADJ", "VERB"})

# spaCy's Portuguese stop list is not usable as the filter here. Of twenty
# ordinary content nouns, it marks twelve as stopwords, `estado`, `apoio`,
# `valor`, `parte` and `area` among them, and those are exactly the words
# Brazilian political and economic coverage turns on. It also misses `dever`,
# `haver` and `ficar`. So the structural filtering happens by part of speech,
# and this short list removes the light verbs that survive it.
#
# A curated list of function words is safe in a way a curated list of topic
# terms is not: the verbs that carry no subject today still carry none in three
# months, so this one does not rot.
LIGHT_VERBS = frozenset(
    {
        "ser",
        "estar",
        "ter",
        "haver",
        "ir",
        "vir",
        "ficar",
        "fazer",
        "dizer",
        "poder",
        "dever",
        "dar",
        "ver",
        "saber",
    }
)

# Short tokens are usually noise, but Brazilian news runs on acronyms: PT, PF,
# STF, PIB. An all-caps original survives regardless of length.
MIN_LENGTH = 3


@functools.lru_cache(maxsize=1)
def _nlp():
    """Loads the model once per process.

    The parser and the entity recognizer cost time and buy nothing here: the
    rule-based lemmatizer needs the tagger and the morphologizer, not a
    dependency tree.
    """
    return spacy.load(MODEL, disable=["parser", "ner"])


def lemmatize(text: str) -> list[str]:
    """Reduces text to its topic-carrying lemmas, lowercased."""
    if not text or not text.strip():
        return []

    lemmas = []
    for token in _nlp()(text):
        if token.pos_ not in CONTENT_POS:
            continue

        lemma = token.lemma_.lower().strip()
        if not lemma or lemma in LIGHT_VERBS:
            continue
        if len(lemma) < MIN_LENGTH and not token.text.isupper():
            continue

        lemmas.append(lemma)

    return lemmas


def term_frequencies(lemmas: list[str]) -> dict[str, float]:
    """Counts lemmas and normalizes by the total, so the vector sums to one.

    Normalizing here means a long summary and a short one are compared by
    proportion instead of by length.
    """
    if not lemmas:
        return {}

    counts = Counter(lemmas)
    total = sum(counts.values())
    return {term: count / total for term, count in counts.items()}
