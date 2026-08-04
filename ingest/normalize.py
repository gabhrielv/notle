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
from dataclasses import dataclass, field
from typing import NamedTuple

import spacy

# Symbols and emoji clinging to the edge of a lemma. Kept off the inside so a
# hyphenated name or a multi-word entity survives intact.
_EDGE_NOISE = re.compile(r"^[^\w]+|[^\w]+$")

# One model per language the corpus carries. The technology feeds publish in
# English, and running Portuguese over English does not merely do worse, it
# invents: `build` comes back as `buildr`, `tighten` as `tightem`, and plurals
# survive untouched, so `model` and `models` become two terms that never meet.
# That is precisely the failure lemmatisation exists to prevent, arriving in the
# other language.
MODELS = {
    "pt": "pt_core_news_sm",
    "en": "en_core_web_sm",
}

DEFAULT_LANGUAGE = "pt"

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
        # Headline verb. Across eight articles carrying it, not one is about
        # choosing: an indigenous lawyer takes over a programme, a party makes
        # its candidate official, Lula speaks for 62 minutes. It reached the
        # strongest terms of a seeded profile and made the card tell a reader
        # they follow "choosing", which is the failure this list exists to stop.
        "escolher",
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
# Verbs and nouns of invitation. They ask the reader to do something with the
# page and never say anything about the story, which is the same category `leia`
# is in. Found by reading the co-occurrence table: the strongest neighbours of
# `google` came back as `favorite`, `acompanhar`, `perca` and `noticia`, because
# every portal ends its technology articles the same way.
#
# Curated, and safe to curate for the reason the architecture already gives: the
# words that ask for a click today will still be asking in three months. It is a
# list of topic terms that rots, not a list of function words.
CHROME = frozenset(
    {
        "leia",
        "ler",
        "acompanhar",
        "favorite",
        "favoritar",
        "perca",
        "notícia",
        "siga",
        "seguir",
        "participe",
        "participar",
        "confira",
        "conferir",
        "veja",
        "saiba",
        "clicar",
        "reprodução",
        "foto",
        "segunda-feira",
        "terça-feira",
        "quarta-feira",
        "quinta-feira",
        "sexta-feira",
        "sábado",
        "domingo",
    }
)

# The same three categories in English, for the technology feeds. Shorter
# because English morphology hides less: spaCy reduces `says`, `said` and
# `saying` to `say` without help, so only the words themselves need naming.
#
# `say` earns its place the way `afirmar` did. Headlines in this register are
# built on attribution, and `sources say` names who spoke, never what happened.
EN_LIGHT_VERBS = frozenset(
    {
        "be",
        "have",
        "do",
        "make",
        "get",
        "go",
        "come",
        "take",
        "give",
        "know",
        "think",
        "see",
        "want",
        "use",
        "need",
        "let",
        # Measured, not guessed. These reached the forty most widespread terms of
        # the English corpus, above every company name in it: `work` in 24
        # articles, `call` in 13, `look` in 12. They are the verbs a technology
        # headline is built from and they name nothing a reader could follow.
        "look",
        "seem",
        "become",
        "keep",
        "put",
        "bring",
        "try",
        "find",
        "help",
        "show",
        "turn",
        "leave",
        "feel",
        "add",
        "start",
        "call",
        "work",
        "mean",
        "ask",
        "hold",
    }
)

# `accord` is the lemma of "according to", the construction attributed reporting
# is built on. It names that someone was quoted, never who or about what.
EN_REPORTING_VERBS = frozenset(
    {"say", "tell", "report", "announce", "claim", "state", "accord"}
)

# Chrome the technology press pastes around a story. `read` is the tail of "read
# more", and weekdays are temporal furniture in any language: nearly every
# article names one, so naming one separates nothing.
EN_CHROME = frozenset(
    {
        "read",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "today",
        "week",
        # Comparatives and temporal furniture. `new` led the whole English corpus
        # at 36 articles and `more` reached 22, which is more document spread than
        # any real subject has. A term that common separates nothing.
        "new",
        "more",
        "most",
        "first",
        "last",
        "next",
        "late",
        "early",
        "good",
        "bad",
        "big",
        "large",
        "small",
        "best",
        "top",
        "time",
        "year",
        "month",
        "day",
        "hour",
        "weekend",
        "morning",
        "night",
        "world",
        "life",
        # The commerce the technology press runs beside the story. `coupon`
        # reached 10 articles on its own, which is a deals widget leaking into a
        # feature space that is supposed to be about subjects.
        "coupon",
        "deal",
        "discount",
        "sale",
        "review",
        # Invitations to act on the page, the English half of what `leia` and
        # `acompanhar` cover above.
        "subscribe",
        "newsletter",
        "sign",
        "follow",
        "comment",
        "click",
        "link",
        "post",
        "article",
        "story",
        "update",
        "guide",
        "roundup",
        "video",
        "photo",
        "image",
        "editor",
        "staff",
    }
)

DISCARDED = {
    "pt": LIGHT_VERBS | REPORTING_VERBS | CHROME,
    "en": EN_LIGHT_VERBS | EN_REPORTING_VERBS | EN_CHROME,
}

# Function words that entity recognition sweeps into a span. spaCy hands back
# `de Sao Paulo` as one location, and merging that verbatim produces a token
# whose part of speech is the preposition's, which the content filter then
# throws away. Trimming the edge first is what keeps the place name.
SPAN_EDGE_POS = frozenset({"ADP", "DET"})

# Entity labels that measure rather than name. Merging them produces terms like
# `august 2026`, which reached the forty most widespread terms of the English
# corpus by appearing in twelve articles: every story published that month
# carries it, so it groups the calendar instead of the subject.
#
# Listing months would not have fixed it. The span is what the model recognized,
# and the parts left behind after refusing to merge are still `august` and
# `2026`, so the tokens have to be dropped by label rather than by spelling.
#
# Inert for Portuguese: that model emits only LOC, MISC, ORG and PER, so none of
# these labels can match and the branch costs a comparison.
UNTOPICAL_ENTS = frozenset(
    {"DATE", "TIME", "PERCENT", "MONEY", "QUANTITY", "ORDINAL", "CARDINAL"}
)

# Short tokens are usually noise, but Brazilian news runs on acronyms: PT, PF,
# STF, PIB. An all-caps original survives regardless of length.
MIN_LENGTH = 3

# What closes a sentence, and therefore what capitalizes the next word for a
# reason that has nothing to do with the word.
#
# Worked out here rather than read off `token.is_sent_start`, because the parser
# is disabled and no other component in either model segments sentences. Without
# it spaCy marks only the very first token of the document, so the word after a
# full stop, which is most of the ones this matters for, would look like it sat
# mid sentence.
_SENTENCE_END = frozenset({".", "!", "?", "…", ";"})


@functools.lru_cache(maxsize=len(MODELS))
def _nlp(language: str = DEFAULT_LANGUAGE):
    """Loads the model once per process.

    The dependency parser is dead weight for lemmas, but entity recognition
    earns its cost: it is what holds `Sao Paulo` together as one term instead
    of two meaningless ones. This runs in the ingestion job, where time is
    free, never inside a request.
    """
    return spacy.load(MODELS.get(language, MODELS[DEFAULT_LANGUAGE]), disable=["parser"])


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
            if entity.label_ in UNTOPICAL_ENTS:
                continue
            for span in _segments(entity):
                while len(span) > 1 and span[0].pos_ in SPAN_EDGE_POS:
                    span = span[1:]
                if len(span) > 1:
                    retokenizer.merge(span, attrs={"LEMMA": span.text})


class Occurrence(NamedTuple):
    """One kept token, with the evidence needed to canonize its lemma later.

    `surface` is the word as the portal wrote it, lowercased. It is the key the
    vote groups by, and lowercasing it is the point rather than tidiness: the
    capital is exactly the accident being corrected for, so `Equipes` opening a
    headline and `equipes` inside one have to land in the same bucket.
    """

    surface: str
    lemma: str
    opens_sentence: bool


def occurrences(text: str, language: str = DEFAULT_LANGUAGE) -> list[Occurrence]:
    """Every topic-carrying token, with its surface and where it sat.

    `language` selects the model and the discard list together, because the two
    have to agree: an English discard list applied to Portuguese output removes
    nothing, and the reverse removes nothing either.
    """
    if not text or not text.strip():
        return []

    discarded = DISCARDED.get(language, DISCARDED[DEFAULT_LANGUAGE])
    doc = _nlp(language)(text)
    _merge_entities(doc)

    kept = []
    # The first token of the text opens a sentence the same way the token after
    # a full stop does, and the pipeline hands this function `title. summary`,
    # so both halves start one.
    opening = True

    for token in doc:
        if token.is_punct:
            # Only a terminator opens the next sentence. A comma or a quote
            # leaves the following word where it was.
            if token.text in _SENTENCE_END:
                opening = True
            continue

        at_opening, opening = opening, False

        if token.pos_ not in CONTENT_POS:
            continue
        # Left unmerged above, so the pieces are still here as ordinary proper
        # nouns and have to be refused by the label they carry.
        if token.ent_type_ in UNTOPICAL_ENTS:
            continue

        lemma = _EDGE_NOISE.sub("", token.lemma_.lower().strip())
        if not lemma or lemma in discarded:
            continue
        # A portal prefixes summaries with an emoji, and it rode into an entity
        # span. A term the reader cannot pronounce explains nothing.
        if not any(character.isalpha() for character in lemma):
            continue
        if len(lemma) < MIN_LENGTH and not token.text.isupper():
            continue

        surface = _EDGE_NOISE.sub("", token.text.lower().strip())
        kept.append(Occurrence(surface, lemma, at_opening))

    return kept


def lemmatize(text: str, language: str = DEFAULT_LANGUAGE) -> list[str]:
    """Reduces text to its topic-carrying lemmas, lowercased."""
    return [found.lemma for found in occurrences(text, language)]


# How many mid sentence readings a written word needs before its vote counts.
#
# Not a threshold to calibrate against an outcome, a floor under the evidence. A
# surface read once mid sentence elects that reading unopposed, and the corpus
# has readings that are simply wrong: `chance` came back as `chancer` on its
# single settled occurrence in the headline sample, which would then have become
# the canonical form of a common word on the strength of one observation.
#
# Three is where a majority can exist without being a coin flip. The archive
# carries summaries as well as headlines, where the same word appears mid
# sentence many times over, so this only ever excludes the genuinely rare.
MIN_SETTLED = 3


@dataclass
class SurfaceVotes:
    """What one written word lemmatized to when the capital carried meaning.

    Only the mid sentence readings are counted. The ones taken at the head of a
    sentence are the readings under suspicion, so letting them vote would be
    asking the error to confirm itself.
    """

    settled: Counter = field(default_factory=Counter)


def tally(votes: dict[str, SurfaceVotes], found: list[Occurrence]) -> None:
    """Adds one article's readings to the poll."""
    for occurrence in found:
        if not occurrence.opens_sentence:
            votes.setdefault(occurrence.surface, SurfaceVotes()).settled[occurrence.lemma] += 1


def canonical_map(votes: dict[str, SurfaceVotes]) -> dict[str, str]:
    """The term each written word should reduce to, whatever the tagger says.

    The corpus splits a term in two whenever the tagger reads the same written
    word differently at the head of a headline than inside one, and Brazilian
    headlines lead with the subject, so this lands on exactly the names that
    matter. `Petrobras anuncia` tags as a common noun and lemmatizes to
    `petrobra`; `da Petrobras` mid sentence stays `petrobras`. `Equipes de
    resgate` keeps its plural; `as equipes de resgate` reduces to `equipe`.

    The two directions have opposite fixes, which is why no rewriting of the
    text can serve both. Prefixing the headline so the first word stops being
    first recovers `petrobras` and leaves `equipes` untouched; lowercasing the
    first word recovers `equipe` and destroys the entity `Petrobras` along with
    `Rio Grande do Sul`. What separates them is not in the sentence, it is in
    the rest of the corpus, which is what this reads.

    So each written word elects one term, by majority of the readings taken
    where its capital was informative. The map is keyed by the written word and
    not by the lemma, and that is the whole safety of it:

        Two different written words can never merge. `santos` electing `santos`
        says nothing about the word `santo`, which is a different string on the
        page and holds its own vote. Keyed by lemma this fails, and it failed
        when measured: the surface `santos` read `santo` once out of seven and
        proposed rewriting every `santo` in the corpus into the football club.
        The same protection covers `deu` against `deus` and `mina` against
        `minas` without naming any of them.

        Nothing mid sentence is ever rewritten. The map is applied only where
        the error lives, so a wrong entry can reach only the openings of that
        one written word rather than every occurrence of a term.

    What this makes true is consistency, not linguistic correctness. A written
    word that always reduces to the same term is a term that matches across
    articles, and matching is what the cosine measures. Picking the prettier of
    two readings is not the job.

    Returns the written word, lowercased, to the term it should produce.
    """
    canonical = {}
    for surface, vote in votes.items():
        if sum(vote.settled.values()) < MIN_SETTLED:
            continue
        # Ties break on the term itself, so two runs over the same corpus agree.
        best = max(vote.settled.items(), key=lambda item: (item[1], item[0]))[0]
        canonical[surface] = best

    return canonical


def canonize(found: list[Occurrence], canonical: dict[str, str]) -> list[str]:
    """The lemmas of `found`, with sentence openings held to the corpus vote.

    Takes occurrences rather than lemmas because the written word is the key,
    and by the time a lemma exists that word has been thrown away.
    """
    return [
        canonical.get(occurrence.surface, occurrence.lemma)
        if occurrence.opens_sentence
        else occurrence.lemma
        for occurrence in found
    ]


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
