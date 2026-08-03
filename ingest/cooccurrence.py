"""Which terms travel together, computed in bulk once a week.

This is what stands in for collaborative filtering, and the substitution is not
a compromise. Collaborative filtering is blocked here twice over. Anonymous
visitors on a portfolio demo mean a population of dozens and a user/item matrix
over 99% empty, which produces coincidence rather than recommendation. And news
dies in 48 hours, while item-item collaborative filtering needs co-occurrence to
accumulate over time: by the time it has, the article is a historical artifact.
Real news systems do not do collaborative filtering at the article level, and
this is why.

The corpus itself is the population instead. If `selic` appears alongside
`cambio` and `inflacao` across thousands of articles, a profile built on one can
reach the others, and the reader is offered a neighbouring subject they never
touched. That delivers adjacent discovery, stays explainable, and depends on no
crowd at all.

**It is not collaborative filtering and this module does not call it that.**

Weekly and in bulk rather than pair by pair during ingestion. An article of
around 28 terms carries some 378 pairs, so updating incrementally at 300
articles a day would be over a hundred thousand writes daily for a statistic
that barely moves. The batch drops that by orders of magnitude and loses nothing
anybody could notice.
"""

from collections import Counter, defaultdict
from itertools import combinations

from ingest.normalize import DISCARDED

# Everything the normalizer would throw away today, in every language it knows.
#
# Applied here as well as there because the two act at different times.
# `article_terms` holds what the normalizer decided when the article arrived, so
# adding a word to the discard list only changes what is stored from then on,
# and the corpus already written keeps its copy. Filtering here fixes the table
# on the next weekly run instead of waiting for the archive to turn over.
STRUCTURAL = frozenset().union(*DISCARDED.values())

# How often a term has to appear before its neighbours mean anything.
#
# Of 18195 terms in the corpus, 4730 reach three documents, 3025 reach five and
# 1683 reach ten. A term seen in two articles has one co-occurring set and no
# evidence: whatever shares those two articles scores perfectly against it.
# Below this line the table would fill with noise that is expensive to store and
# actively harmful to expand a profile with.
MIN_DOC_COUNT = 5

# How many portals have to have used a term before it can be somebody's
# neighbour.
#
# The same structural test the onboarding uses, and for the same reason: what one
# portal alone says is that portal's furniture, not a subject. Without it, the
# strongest neighbour of `google` came back as `favorite o g1`, at 0.51, because
# G1 pastes that line into its technology articles and Dice cannot tell a habit
# of the newsroom from a habit of the language.
#
# It costs 304 of 3025 terms, and reading them shows what they are: `reproducao`,
# `siga`, `participe`, `23h00`, `fotos`, `nublado`. A few real ones go with them,
# `corpo de bombeiros` among them, and that is an acceptable loss because the
# filter applies only here. Those terms still rank and still match a search; they
# just do not get offered as an adjacent subject.
MIN_SOURCES = 2

# How many neighbours each term keeps.
#
# The write cost is the constraint. D1 binds 100 parameters, so three columns
# means 33 rows per request, and 3025 terms at eight neighbours is around 24
# thousand rows and 730 requests. That is minutes inside a weekly job and
# unthinkable inside an hourly one.
NEIGHBOURS = 8

# Below this the pair is a coincidence rather than a habit.
#
# Dice runs in [0, 1], so this is readable directly: two terms have to share at
# least this share of their appearances before one is offered as the other's
# neighbour.
MIN_SCORE = 0.08


def dice(together: int, docs_a: int, docs_b: int) -> float:
    """How much two terms share their appearances, in [0, 1].

    Dice rather than raw counts or PMI. Raw counts make every term's neighbours
    the corpus's commonest words, so `selic` would come back next to `governo`
    and `ano` and expanding a profile would drag it to the centre instead of
    sideways. PMI captures specific pairs better but rewards coincidence: a pair
    seen twice, in the only two articles either term appeared in, scores at the
    top. Dice cannot do that, because the denominator is the appearances
    themselves.
    """
    total = docs_a + docs_b
    return (2 * together) / total if total else 0.0


def count_pairs(articles: dict[int, set[str]], eligible: set[str]) -> Counter:
    """How many articles each pair of eligible terms shares.

    Filtering to eligible terms before pairing rather than after is what keeps
    this tractable: the full vocabulary would pair 18 thousand terms where the
    eligible set pairs three thousand, and the work is quadratic in what each
    article contributes.
    """
    pairs: Counter = Counter()

    for terms in articles.values():
        present = sorted(terms & eligible)
        pairs.update(combinations(present, 2))

    return pairs


def strongest_neighbours(
    pairs: Counter,
    document_counts: dict[str, int],
    limit: int = NEIGHBOURS,
) -> list[tuple[str, str, float]]:
    """The rows `term_cooccur` should hold.

    Both directions are written. The table is read by `term_a` and a profile
    holding either side has to be able to reach the other, so storing one
    direction would make expansion depend on alphabetical order.

    Ties break on the neighbour's own name, so two runs over one corpus produce
    the same table.
    """
    by_term: dict[str, list[tuple[float, str]]] = defaultdict(list)

    for (a, b), together in pairs.items():
        score = dice(together, document_counts.get(a, 0), document_counts.get(b, 0))
        if score < MIN_SCORE:
            continue
        by_term[a].append((score, b))
        by_term[b].append((score, a))

    rows = []
    for term, neighbours in by_term.items():
        neighbours.sort(key=lambda pair: (-pair[0], pair[1]))
        rows.extend((term, other, score) for score, other in neighbours[:limit])

    return rows


def eligible_terms(
    document_counts: dict[str, int], source_counts: dict[str, int] | None = None
) -> set[str]:
    """The terms both frequent enough and shared enough to have neighbours.

    `source_counts` is how many distinct portals used each term. Absent, only
    frequency is applied, which is what the unit tests exercise.
    """
    source_counts = source_counts or {}

    return {
        term
        for term, count in document_counts.items()
        if count >= MIN_DOC_COUNT
        and term not in STRUCTURAL
        and source_counts.get(term, MIN_SOURCES) >= MIN_SOURCES
    }
