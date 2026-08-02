"""Turns affinity and age into a position in the feed.

    score = (W_GOSTO * cosine(profile, cluster) + W_RECENCIA) * decay(age)
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
# Which makes it measurable instead of a matter of taste. Against the 252
# candidates in the live window, with profiles built the way a like builds them,
# as the mean of the vectors of the clusters the reader kept, the cosine between
# a profile and a candidate came out:
#
#     max 0.155   p99 0.069   p95 0.042   p90 0.028   median 0.001
#
# It sits far below the 0.25 to 0.67 that two articles about the same event score
# against each other, and for a plain reason: a profile of a few terms is being
# compared against a headline vector of around twenty six, so the overlap is
# thin even when the subject is right.
#
# 0.025 sits just under that p90 of 0.028, so a candidate in the top tenth of
# affinity clears the bar and is worth twelve hours of age, while everything
# below it is ordered by freshness. Rounding to 0.03 instead would put the bar
# above the p90 and quietly make that sentence false, which is the kind of two
# thousandths that a comment claims and nothing checks.
#
# The first value tried here was 0.10, above the p99 and near the observed
# maximum. It made the profile decorative: nothing the reader liked could ever
# outrank a fresh story about nothing they cared about.
#
# Still provisional, and still one of the constants the persona simulator is
# meant to settle. What changed is that it is now a measurement with a stated
# meaning rather than a number someone liked the look of.
W_GOSTO = 1.0
W_RECENCIA = 0.025

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
NEGATIVE_FLOOR = 0.10

# What a hidden subject costs a story that genuinely resembles it.
#
# Read the same way W_RECENCIA is, as a sentence that can be checked:
#
#     BETA sets what the strongest possible resemblance costs, and at 0.2 that
#     is about one half life of freshness.
#
# The first value tried here was 1.0, on the argument that it is symmetric with
# W_GOSTO and that `like` and `hide` weigh the same in the log. The argument was
# right about the two cosines and wrong about the score they are subtracted
# from. An untouched story of this moment scores W_RECENCIA, which is 0.025, so
# a penalty of 0.005 for sharing the word `experiencia` already put a card below
# everything fresh. One hide removed 294 stories, and the explanation the card
# was supposed to carry never reached a screen, because a penalised card can
# never outrank an unpenalised one.
#
# At 0.2 the worst case costs 0.031 against a floor of 0.025. The story drops,
# and stays where it can be seen dropping, which is what "menos relevante"
# claims and what banishment does not.
#
# The penalty sits outside the decay, and that is deliberate. Inside it, a
# rejected story would be forgiven for getting old, and the feed would drift
# back toward exactly the subject the reader asked it to drop.
BETA = 0.2

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


def rejection(negative_cosine: float) -> float:
    """How much of a negative cosine counts, which below the floor is none.

    A hard cut rather than a taper. A taper would still let a card lose a little
    for sharing the word `experiencia`, and the card names its reasons on screen,
    so any penalty worth applying has to be one worth printing.
    """
    return negative_cosine if negative_cosine >= NEGATIVE_FLOOR else 0.0


def score(similarity_value: float, age_hours: float, penalty: float = 0.0) -> float:
    """Where a candidate lands: how well it matches, how old it is, what it recalls.

    `penalty` is the cosine against the reader's negative profile, in [0, 1],
    already through `rejection`. It defaults to zero because most visitors have
    hidden nothing, and that path should read as the same expression with one
    term absent rather than as a branch.
    """
    return (W_GOSTO * similarity_value + W_RECENCIA) * decay(age_hours) - BETA * penalty


def age_in_hours(published_at: str, now: datetime) -> float:
    """Hours between a stored timestamp and the moment of the request.

    The corpus writes UTC with a trailing Z, which `fromisoformat` reads
    directly from Python 3.11 on. Parsing by hand would be faster to defend as
    cheap and much harder to defend as correct.
    """
    return (now - datetime.fromisoformat(published_at)).total_seconds() / 3600.0
