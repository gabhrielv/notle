"""Turns affinity and age into a position in the feed.

    score = (W_GOSTO   * cosine(profile,          cluster)
            + W_SESSAO  * cosine(session_profile,  cluster)   # adaptativo, teto 0.35
            + W_COOCOR  * cosine(expanded_profile, cluster)
            + W_RECENCIA) * decay(age)
            - BETA * cosine(negative_profile, cluster)

The recency floor sits inside the decay rather than beside it, and that is the
whole reason the formula holds together for a visitor who has done nothing yet.
Every visitor is anonymous, so every visitor starts with an empty profile, every
cosine is exactly zero, and every candidate ties. With the floor inside, what
survives is `W_RECENCIA * decay(age)`, which orders by freshness. The cold start
needs no branch anywhere: it is the same expression with one term at zero.

Put the floor outside and it becomes a constant added to everyone, ordering
nothing, and the first screen most people ever see would be arbitrary.
"""

from datetime import datetime

# Only the ratio between these two matters, and it has one honest reading.
# Because the decay multiplies the whole sum, floor included, a story with
# affinity `c` beats an unrelated story one half life fresher exactly when
# `c > W_RECENCIA / W_GOSTO`. So the floor is not a tiebreaker or a nudge:
#
#     W_RECENCIA is the cosine that is worth one half life of staleness.
#
# Which makes it measurable instead of a matter of taste. Measured over twenty
# profiles built the way a like builds them, each the vector of one cluster the
# reader kept, against the 1576 candidates of the live window, which is 11604
# pairs with any overlap at all:
#
#     max 0.381   p99 0.116   p95 0.065   p90 0.044   median 0.011
#
# It sits below the 0.25 to 0.67 that two articles about the same event score
# against each other, and for a plain reason: a profile of a few terms is being
# compared against a headline vector of around twenty six, so the overlap is
# thin even when the subject is right.
#
# 0.04 sits just under that p90 of 0.044, so a candidate in the top tenth of
# affinity clears the bar and is worth twelve hours of age, while everything
# below it is ordered by freshness.
#
# These numbers replace an earlier set, max 0.155 and p90 0.028, and the earlier
# set was not a smaller corpus. It was the dot product being built wrong: the
# candidate's side went into it unweighted while the norm it divided by was
# weighed, which pulled every cosine down by somewhere between three and seven
# times depending on which terms matched. W_RECENCIA was 0.025 then, chosen
# under the same rule against the wrong distribution.
#
# The first value tried was 0.10, above the p99 of that distribution and near
# its maximum. It made the profile decorative: nothing the reader liked could
# ever outrank a fresh story about nothing they cared about.
#
# Still provisional, and still one of the constants the persona simulator is
# meant to settle. What changed is that it is now a measurement with a stated
# meaning rather than a number someone liked the look of.
W_GOSTO = 1.0
W_RECENCIA = 0.04

# Below this, two stories share vocabulary rather than a subject.
#
# Measured by hiding one cluster, "Diego Souza e anunciado como novo tecnico do
# Joinville", and reading every candidate it touched in the live window. It
# reached 294 of 1593, and the ranking of those was not a ranking of football:
#
#     0.139  Pentacampeao passa por cateterismo          the subject
#     0.122  Corinthians: Diniz denunciado no STJD       the subject
#     0.119  Vasco x Fluminense                          the subject
#     ------------------------------------------------- floor
#     0.080  IFMG abre vagas para cursos tecnicos        `tecnico`
#     0.063  Endrick no Real Madrid                      the subject
#     0.056  C6 condenado, aposentado lesado             `aposentar`
#     0.055  Xuxa anuncia terceiro show                  `experiencia`
#
# What sits just under 0.10 is polysemy, which is the standing weakness of a bag
# of lemmas: `tecnico` is a coach and a technical course, `aposentar` is leaving
# football and drawing a pension. A model with no syntax cannot tell those
# apart, so the honest move is to refuse to act on evidence that thin rather
# than to pretend the number means what it does not.
#
# Real coverage of one event scores 0.25 to 0.67 against itself, well clear of
# this, so nothing a reader would recognise as the hidden subject is let through.
#
# This number survived the dot product being fixed, because the table above was
# measured as a true cosine in the first place rather than through the code. It
# was the ranking that disagreed with it, not the measurement.
NEGATIVE_FLOOR = 0.10

# What a hidden subject costs a story that genuinely resembles it.
#
# Read the same way W_RECENCIA is, as a sentence that can be checked:
#
#     BETA sets what the strongest resemblance costs, and at 0.1 that is about
#     one half life of freshness.
#
# The strongest cosine measured across the window was 0.381, so the worst case
# costs 0.038 against a W_RECENCIA of 0.04. Above the floor the penalty runs
# from 0.010 to 0.038: a real demotion, and never more than the whole recency
# floor is worth.
#
# The first value tried here was 1.0, on the argument that it is symmetric with
# W_GOSTO and that `like` and `hide` weigh the same in the log. The argument was
# right about the two cosines and wrong about the score they are subtracted
# from. One hide reached 294 of 1576 candidates and drove every one of them
# below zero.
#
# The penalty sits outside the decay, and that is deliberate. Inside it, a
# rejected story would be forgiven for getting old, and the feed would drift
# back toward exactly the subject the reader asked it to drop.
BETA = 0.1

# What an adjacent subject is worth against one the reader actually chose.
#
# Deliberately the smallest of the three affinity weights. The expanded profile
# is an offer rather than a claim: the reader never touched these subjects, and
# the corpus merely observed that they sit next to something the reader did
# touch. At 0.25 a perfect match on a neighbouring subject is worth a quarter of
# a perfect match on a chosen one, so expansion can lift a story into view and
# can never put it above what the reader asked for.
#
# It also stays under the session cap of 0.35, which keeps the ordering of the
# three honest: what you are reading now says more than what the corpus thinks
# is next door.
W_COOCOR = 0.25

# News dies in 48 hours. At a 12 hour half life a story from two days ago carries
# 6% of the weight of one from now, which is small enough to keep the feed from
# looking stale and large enough that a good old story can still outrank a dull
# fresh one when the profile has an opinion.
HALF_LIFE_HOURS = 12.0


def decay(age_hours: float) -> float:
    """Weight left on a story of this age. A negative age counts as fresh.

    A portal publishing with a clock running ahead would otherwise earn a
    multiplier above one and take the top of the feed on nothing but a bad
    timestamp.
    """
    return 0.5 ** (max(age_hours, 0.0) / HALF_LIFE_HOURS)


def similarity(dot: float, profile_norm: float, cluster_norm: float) -> float:
    """Completes the cosine the database only computed the numerator of.

    The dot product is aggregated in SQL across the inverted index, so the two
    lengths divide it here. `cluster_norm` was written into `feed_candidates` by
    the ingestion, and `profile_norm` is computed per request from the profile.

    A zero length means one side has no terms, which is the empty profile of a
    visitor who just arrived. That is not an error and not a division to
    attempt: it is an affinity of zero, and the recency floor takes over.
    """
    magnitude = profile_norm * cluster_norm
    return dot / magnitude if magnitude else 0.0


# What is left of a story's score after it has been offered this many times.
#
# A schedule rather than a formula, because the numbers were read off the live
# ranking rather than derived. Scores in the window are packed extremely tightly,
# since almost everything is recent and the floor dominates:
#
#     position     1     25     49     97    193    385
#     score    0.0386 0.0358 0.0342 0.0316 0.0275 0.0207
#
# So the size of a penalty is not the interesting quantity; how far it moves a
# card is. The first shape tried here was `1 - shown / 3`, which takes a third
# off at the first impression, and a third is the distance from the top of the
# feed to somewhere past position 250. Measured against the live feed, a story
# shown once vanished beyond the first 192 positions, which means the growing
# penalty and the third showing never happened: everything was decided by the
# first.
#
# These three move a card by roughly a page, then by a few pages, then out. That
# is what makes "a good story does not vanish for having been on screen" true
# while still ending at three.
REPETITION = (1.0, 0.93, 0.85)

# How many times the feed may show one story before it stops offering it.
IMPRESSION_LIMIT = len(REPETITION)


def repetition(shown: int) -> float:
    """What is left of a story's score after it has been offered `shown` times.

    Multiplicative rather than subtracted, and that is not a stylistic choice.
    A subtracted penalty large enough to matter drives the score below zero, and
    under zero the decay inverts: multiplying a negative by a smaller number
    makes it larger, so the staler of two over-shown stories would climb above
    the fresher one. Damping keeps every score on the same side of zero and the
    ordering intact.

    Nothing about this touches the profile. An impression is a consequence of
    the ranking's own choice, so learning from it would be the system measuring
    its own output and calling it taste.
    """
    if shown <= 0:
        return REPETITION[0]
    if shown >= IMPRESSION_LIMIT:
        return 0.0

    return REPETITION[shown]


def rejection(negative_cosine: float) -> float:
    """How much of a negative cosine counts, which below the floor is none.

    A hard cut rather than a taper. A taper would still let a card lose a little
    for sharing the word `experiencia`, and the card names its reasons on screen,
    so any penalty worth applying has to be one worth printing.
    """
    return negative_cosine if negative_cosine >= NEGATIVE_FLOOR else 0.0


def score(
    similarity_value: float,
    age_hours: float,
    penalty: float = 0.0,
    session_value: float = 0.0,
    session_weight: float = 0.0,
    adjacent_value: float = 0.0,
) -> float:
    """Where a candidate lands: how well it matches, how old it is, what it recalls.

    `penalty` is the cosine against the reader's negative profile, in [0, 1],
    already through `rejection`. `session_value` is the cosine against the last
    few minutes and `session_weight` how much this session has earned the right
    to say. All three default to zero because most requests carry none of them,
    and those paths should read as the same expression with terms absent rather
    than as branches.

    The session term sits inside the decay with the long profile rather than
    beside it. A story the reader is on a run about still has to be news: an
    afternoon of reading about one subject must not resurface something from two
    days ago simply because it matches.
    """
    taste = (
        W_GOSTO * similarity_value
        + session_weight * session_value
        + W_COOCOR * adjacent_value
    )
    return (taste + W_RECENCIA) * decay(age_hours) - BETA * penalty


def age_in_hours(published_at: str, now: datetime) -> float:
    """Hours between a stored timestamp and the moment of the request.

    The corpus writes UTC with a trailing Z, which `fromisoformat` reads
    directly from Python 3.11 on. Parsing by hand would be faster to defend as
    cheap and much harder to defend as correct.
    """
    return (now - datetime.fromisoformat(published_at)).total_seconds() / 3600.0
