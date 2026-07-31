"""Turns headline text into the terms that carry topic.

Lemmas, not stems. Portuguese is heavily inflected, so without treatment
`eleicoes` and `eleicao` become two terms that never meet, each holding half the
mass with an inflated IDF. An aggressive stemmer would match them at the cost of
producing `eleic`, and the screen shows this text to the user as the reason a
story ranked where it did.
"""

import functools
import re
from collections import Counter

import spacy

# Symbols and emoji clinging to the edge of a lemma. Kept off the inside so a
# hyphenated name or a multi-word entity survives intact.
_EDGE_NOISE = re.compile(r"^[^\w]+|[^\w]+$")

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

# Verbs of attribution. They mark who said a thing, never what the thing is,
# and `afirmar` alone showed up 137 times across 311 real articles.
REPORTING_VERBS = frozenset({"afirmar", "declarar", "informar", "apontar", "contar"})

# Chrome the portals paste around the story rather than into it.
#
# `leia` is the tail of "Leia tambem" and "Leia mais", and it appeared in 129 of
# 311 real articles, more document spread than any actual topic. Weekdays are
# temporal furniture: nearly every article names one, so naming one separates
# nothing. Months are deliberately absent from this list because `janeiro` is
# part of `Rio de Janeiro`.
CHROME = frozenset(
    {
        "leia",
        "ler",
        "segunda-feira",
        "terça-feira",
        "quarta-feira",
        "quinta-feira",
        "sexta-feira",
        "sábado",
        "domingo",
    }
)

DISCARDED = LIGHT_VERBS | REPORTING_VERBS | CHROME

# Function words that entity recognition sweeps into a span. spaCy hands back
# `de Sao Paulo` as one location, and merging that verbatim produces a token
# whose part of speech is the preposition's, which the content filter then
# throws away. Trimming the edge first is what keeps the place name.
SPAN_EDGE_POS = frozenset({"ADP", "DET"})

# Short tokens are usually noise, but Brazilian news runs on acronyms: PT, PF,
# STF, PIB. An all-caps original survives regardless of length.
MIN_LENGTH = 3


@functools.lru_cache(maxsize=1)
def _nlp():
    """Loads the model once per process.

    The dependency parser is dead weight for lemmas, but entity recognition
    earns its cost: it is what holds `Sao Paulo` together as one term instead
    of two meaningless ones. This runs in the ingestion job, where time is
    free, never inside a request.
    """
    return spacy.load(MODEL, disable=["parser"])


def _segments(entity):
    """Splits an entity span at punctuation.

    Headlines separate the subject from the statement with a colon, and entity
    recognition reads straight through it. "Selic: Copom mantem os juros" comes
    back as a single entity, and merging it verbatim produces the term
    `selic: copom`, which no other article can ever share. The story then fails
    to group with the same story from another portal, and it fails for a reason
    invisible on the screen.

    Splitting first leaves `selic` and `copom` as the two terms that carry it,
    and a name that happens to sit after the colon still merges on its own.
    """
    start = 0
    for index, token in enumerate(entity):
        if token.pos_ != "PUNCT":
            continue
        if index > start:
            yield entity[start:index]
        start = index + 1

    if start < len(entity):
        yield entity[start:]


def _merge_entities(doc) -> None:
    """Collapses multi-word entities into single tokens, in place.

    The merged token takes the span's surface text as its lemma rather than the
    concatenation of its parts' lemmas. Lemmatizing inside a name expands the
    contraction in `Rio Grande do Sul` into `rio grande de o sul`, which is not
    a phrase any reader would recognize as the state they live in.
    """
    with doc.retokenize() as retokenizer:
        for entity in doc.ents:
            for span in _segments(entity):
                while len(span) > 1 and span[0].pos_ in SPAN_EDGE_POS:
                    span = span[1:]
                if len(span) > 1:
                    retokenizer.merge(span, attrs={"LEMMA": span.text})


def lemmatize(text: str) -> list[str]:
    """Reduces text to its topic-carrying lemmas, lowercased."""
    if not text or not text.strip():
        return []

    doc = _nlp()(text)
    _merge_entities(doc)

    lemmas = []
    for token in doc:
        if token.pos_ not in CONTENT_POS:
            continue

        lemma = _EDGE_NOISE.sub("", token.lemma_.lower().strip())
        if not lemma or lemma in DISCARDED:
            continue
        # A portal prefixes summaries with an emoji, and it rode into an entity
        # span. A term the reader cannot pronounce explains nothing.
        if not any(character.isalpha() for character in lemma):
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
