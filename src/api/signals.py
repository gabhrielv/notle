"""The implicit half of the funnel: what a reader did without saying anything.

Four things get measured, and each one filters the one before it. A card enters
the viewport, is dwelt on, is clicked, and the reader either comes straight back
or does not. Nothing here is a statement, which is the whole difficulty: every
value is a guess about intent read off a browser event, and browsers lie about
intent all the time.

So the rule the architecture states is enforced here as arithmetic rather than
as intention:

    Implicit adjusts, explicit decides. No implicit signal, alone or combined,
    can reorder two stories that carry different explicit signals.

`CEILING` is that sentence as an inequality, and a test holds it.

Large systems tolerate noisy implicit signals because the error cancels across
millions of events. This one will not have the volume, so low weights are not
timidity; they are the only defensible posture at this scale.
"""

# What a card being on screen is worth to the profile. Zero, and not as a
# placeholder.
#
# If an impression fed the profile the loop would close: the ranking shows what
# the reader already likes, the display confirms they like it, the profile
# tightens, the ranking shows more of the same. An impression is not a
# preference, it is a consequence of the ranking's own choice, and a system that
# learns from it is measuring its own output and calling it taste.
IMPRESSION = 0.0

# How much a card dropping out of sight after being read is worth.
#
# Normalized by how much text the card actually shows. Unnormalized, this does
# not measure interest, it measures how much a portal writes: a reader spends
# more seconds on the longer headline, the weight climbs, and in two weeks the
# ranking has learned a source preference nobody has. The bias is invisible
# while it installs itself, because every engagement metric goes up.
#
# The architecture says to normalize by the summary, and the card does not show
# one: it shows the cluster's terms, the headline and the byline. So the
# divisor is the headline, which is the text the reader is actually spending
# the seconds on. Normalizing by text that is not on screen would be correcting
# for a bias that is not there and leaving the real one alone.
DWELL_MAX = 0.15

# Leaving for the portal. The strongest thing a reader does without saying
# anything, and still under half a like.
CLICK = 0.40

# Coming back long enough to have read something.
#
# Saturates rather than scaling with time, because the difference between two
# minutes and twenty is not twice the interest; it is a tab left open.
RETURN_MAX = 0.30

# Below this, a return has one plausible reading, and it is rejection. The click
# is cancelled and a little is taken off besides.
RETURN_QUICK_SECONDS = 15.0

# Above this, the reader was reading.
RETURN_READ_SECONDS = 60.0

# Above this, they finished. The credit stops climbing here rather than at the
# discard cutoff, and the gap between the two is deliberate: with the peak at the
# cutoff, the most valuable possible return would be one second before it became
# worthless, which is a cliff disguised as a curve.
RETURN_FULL_SECONDS = 180.0

# Above this the event is thrown away rather than guessed at.
#
# A return after four minutes has ten explanations and reading is not the
# likeliest: a message answered, a phone in a pocket, lunch. The asymmetry is the
# point. Short returns mean one thing; long ones mean nothing, so only the half
# that carries information is used.
RETURN_STALE_SECONDS = 300.0

# What a click that was regretted costs. It cancels the click and leaves a
# little behind, which is what "anula o click" plus "negativo fraco" means.
RETURN_QUICK = 0.10

# The bound the whole module exists to respect.
#
# Every implicit weight a single cluster can accumulate has to stay under the
# smallest explicit one, which is a like at 1.0. Dwell, click and a long return
# are the only three that can land together on one cluster, and an impression
# adds nothing by construction.
CEILING = 1.0

# What the reader is allowed to report. Named here rather than inferred, so a
# client cannot invent a signal type and have it stored.
IMPLICIT = ("impression", "dwell", "click", "return")


def dwell_value(seconds: float, text_length: int) -> float:
    """How much time on a card is worth, per word shown rather than raw.

    A card reporting no text at all still gets a nominal length rather than
    being dropped: it was on screen and it was read, and the client failing to
    measure its own headline is not the reader's doing.
    """
    if seconds <= 0:
        return 0.0

    words = max(text_length, 1) / 5.5
    per_word = seconds / max(words, 1.0)

    # Two seconds per word is thorough reading; beyond that the reader stopped
    # looking at the screen rather than kept reading it.
    return min(per_word / 2.0, 1.0) * DWELL_MAX


def return_value(seconds: float) -> float:
    """What coming back is worth, positive or negative, or nothing at all.

    Returns a signed number. Negative means the click before it was a mistake,
    and the caller stores it as such.
    """
    if seconds < 0 or seconds > RETURN_STALE_SECONDS:
        return 0.0
    if seconds < RETURN_QUICK_SECONDS:
        return -(CLICK + RETURN_QUICK)
    if seconds < RETURN_READ_SECONDS:
        return 0.0

    # Saturating: the whole of RETURN_MAX is reached three minutes in and never
    # exceeded, so a tab left open all afternoon is worth what a real read is.
    span = RETURN_FULL_SECONDS - RETURN_READ_SECONDS
    return RETURN_MAX * min((seconds - RETURN_READ_SECONDS) / span, 1.0)


# How many events one request may carry. The client batches, so a page of
# reading arrives as a few dozen rows; past this the payload is a mistake or an
# attempt, and either way it is truncated rather than refused, so a bug in the
# client costs the reader nothing.
MAX_BATCH = 120


def _seconds(raw, ceiling: float) -> float | None:
    """A duration the client sent, in seconds, clamped and never trusted.

    `None` for anything unusable, and the distinction from zero is load bearing.
    Read as zero, a missing duration becomes "came back instantly", which is the
    strongest rejection the funnel can express. A bug in the client would then
    quietly punish every story it touched.
    """
    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        return None
    if raw != raw or raw < 0:
        return None
    return min(float(raw) / 1000.0, ceiling)


def score_event(event) -> tuple[str, int, float, int] | None:
    """Turns one reported event into a row, or into nothing.

    The value is computed here rather than accepted from the client, and that is
    the whole reason this function exists. A browser reporting how much a signal
    was worth would be a browser writing directly into someone's taste profile.
    What the client is allowed to say is what happened and for how long.
    """
    if not isinstance(event, dict):
        return None

    kind = event.get("type")
    cluster_id = event.get("cluster_id")

    if kind not in IMPLICIT or not isinstance(cluster_id, int) or isinstance(cluster_id, bool):
        return None

    if kind == "impression":
        return kind, cluster_id, IMPRESSION, 0

    if kind == "click":
        return kind, cluster_id, CLICK, 0

    # An hour is past every threshold that means anything, so clamping there
    # loses no signal and bounds what a bad clock can claim.
    seconds = _seconds(event.get("duration_ms"), 3600.0)
    if seconds is None:
        return None

    if kind == "dwell":
        length = event.get("text_length")
        length = length if isinstance(length, int) and not isinstance(length, bool) else 0
        value = dwell_value(seconds, length)
        return (kind, cluster_id, value, int(seconds * 1000)) if value else None

    value = return_value(seconds)
    return ("return", cluster_id, value, int(seconds * 1000)) if value else None


def accept(events) -> list[tuple[str, int, float, int]]:
    """The rows a reported batch is allowed to become.

    An impression survives with a value of zero, because the ranking counts the
    rows to stop offering a story a fourth time. Every other signal that scores
    zero is dropped: storing it would fill the log with events that say nothing
    and cost a scan on every profile rebuild.
    """
    if not isinstance(events, list):
        return []

    rows = []
    for event in events[:MAX_BATCH]:
        row = score_event(event)
        if row is not None:
            rows.append(row)

    return rows


def most_one_cluster_can_gather() -> float:
    """The largest implicit total a single cluster can reach.

    Written as a function rather than a constant so the test cannot drift from
    the weights: it recomputes the worst case out of the same numbers the
    scoring uses.
    """
    return DWELL_MAX + CLICK + RETURN_MAX + IMPRESSION
