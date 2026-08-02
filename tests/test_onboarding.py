"""Tests for the headlines the cold start offers.

This is the screen most visitors will only ever see, so what is pinned here is
the property that makes it worth building: that it spans the news instead of
sampling it. Twelve stories about the same thing would seed a narrower profile
than no profile at all.

The numbers quoted come from the live window of 1332 clusters over 24 hours.
"""

from datetime import UTC, datetime

from ingest import onboarding

NOW = datetime(2026, 7, 31, 12, tzinfo=UTC)

# Source ids, so the per portal ceiling can be exercised.
G1, FOLHA, BBC, CNN = 1, 2, 3, 4


def at(hours_ago: float) -> str:
    stamp = NOW.timestamp() - hours_ago * 3600
    return datetime.fromtimestamp(stamp, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def window(*specs):
    """Builds the term rows and the coverage map from one compact spec."""
    rows = []
    coverage = {}
    for cluster_id, terms, hours_ago, portals, source_id in specs:
        for term, tf in terms.items():
            rows.append(
                {
                    "cluster_id": cluster_id,
                    "published_at": at(hours_ago),
                    "term": term,
                    "tf": tf,
                }
            )
        coverage[cluster_id] = (portals, source_id)
    return rows, coverage


def build(*specs, counts=None, total=100):
    rows, coverage = window(*specs)
    counts = counts or dict.fromkeys({row["term"] for row in rows}, 5)
    return onboarding.assemble(rows, coverage, counts, total, NOW)


class TestAssemble:
    def test_groups_rows_into_one_vector_per_cluster(self):
        built = build(
            (1, {"selic": 0.6, "copom": 0.4}, 1, 1, G1),
            (2, {"futebol": 1.0}, 2, 1, FOLHA),
        )

        assert {cluster_id for cluster_id, _, _, _ in built} == {1, 2}

    def test_a_cluster_with_no_length_is_not_offered(self):
        """A term in every document has an IDF of zero, so a vector made only of
        those has no length and no cosine against anything. Offering it would
        seed a profile that matches nothing forever.
        """
        built = build((1, {"governo": 1.0}, 1, 1, G1), counts={"governo": 100})

        assert built == []

    def test_coverage_lifts_a_story_above_a_fresher_one(self):
        """The largest of the three fixes.

        Everything in the window arrived within the hour, so decay runs between
        0.95 and 1.0 and freshness cannot separate 1332 candidates into twelve.
        How many portals ran a story is the corpus's own answer to which of them
        was the day's news.
        """
        built = build(
            (1, {"gaza": 1.0}, 3, 3, CNN),
            (2, {"transito": 1.0}, 0, 1, G1),
        )
        scores = {cluster_id: score for cluster_id, _, score, _ in built}

        assert scores[1] > scores[2]

    def test_a_cluster_with_no_coverage_row_counts_as_one_portal(self):
        rows, _ = window((1, {"selic": 1.0}, 0, 1, G1))
        built = onboarding.assemble(rows, {}, {"selic": 5}, 100, NOW)

        assert len(built) == 1


class TestChoose:
    def test_the_strongest_story_opens_the_screen(self):
        built = build(
            (1, {"selic": 1.0}, 10, 1, G1),
            (2, {"futebol": 1.0}, 1, 1, FOLHA),
        )

        assert onboarding.choose(built)[0] == 2

    def test_a_near_duplicate_loses_to_something_different(self):
        """Cluster 2 is fresher than 3 and would come second on its own score,
        but it is the same story as the one already on the screen. A visitor
        shown two versions of one event learns less than one shown two events.
        """
        built = build(
            (1, {"selic": 1.0}, 0, 1, G1),
            (2, {"selic": 1.0}, 1, 1, FOLHA),
            (3, {"futebol": 1.0}, 5, 1, BBC),
        )

        assert onboarding.choose(built)[:2] == [1, 3]

    def test_the_duplicate_is_still_offered_once_the_spread_runs_out(self):
        """Variety is a preference, not a filter. With room left on the screen a
        repeat beats an empty slot.
        """
        built = build(
            (1, {"selic": 1.0}, 0, 1, G1),
            (2, {"selic": 1.0}, 1, 1, FOLHA),
            (3, {"futebol": 1.0}, 5, 1, BBC),
        )

        assert sorted(onboarding.choose(built)) == [1, 2, 3]

    def test_one_portal_cannot_take_the_whole_screen(self):
        """G1 publishes 678 of the 1332 clusters in the window, more than the
        other five together, so without a ceiling it takes half the screen on
        publishing rate alone.
        """
        built = build(
            *[(i, {f"termo{i}": 1.0}, i * 0.1, 1, G1) for i in range(10)],
            (90, {"outro": 1.0}, 9, 1, FOLHA),
        )
        chosen = onboarding.choose(built)

        assert len(chosen) == onboarding.PER_SOURCE + 1
        assert 90 in chosen

    def test_a_window_from_one_portal_comes_back_short(self):
        """The honest outcome. Relaxing the ceiling to fill the screen would make
        it a suggestion rather than a rule.
        """
        built = build(*[(i, {f"termo{i}": 1.0}, i, 1, G1) for i in range(8)])

        assert len(onboarding.choose(built)) == onboarding.PER_SOURCE

    def test_it_stops_at_the_offer(self):
        built = build(
            *[(i, {f"termo{i}": 1.0}, i * 0.1, 1, i % 6) for i in range(60)]
        )

        assert len(onboarding.choose(built)) == onboarding.OFFER

    def test_nothing_ingested_yet(self):
        assert onboarding.choose([]) == []

    def test_two_runs_over_one_window_choose_the_same_twelve(self):
        """A screen that reshuffles on reload looks random, which is the opposite
        of what this is. Ties break on the cluster id so the answer is fixed.
        """
        built = build(
            *[(i, {f"termo{i % 5}": 1.0}, 3, 1, i % 6) for i in range(20)]
        )

        assert onboarding.choose(built) == onboarding.choose(list(reversed(built)))


class TestMaterialize:
    def test_the_offer_is_replaced_rather_than_added_to(self):
        """The window slides every hour, so most of what changes is which rows
        belong at all, exactly as with feed_candidates.
        """
        statements = []

        class FakeClient:
            def query(self, sql, params=None):
                statements.append(sql)
                return []

            def insert_many(self, table, columns, rows):
                statements.append(f"INSERT {table} {len(rows)}")

        onboarding.materialize(FakeClient(), [7, 9])

        assert statements[0].startswith("DELETE FROM onboarding_picks")
        assert statements[1] == "INSERT onboarding_picks 2"

    def test_position_is_the_order_it_chose(self):
        written = {}

        class FakeClient:
            def query(self, sql, params=None):
                return []

            def insert_many(self, table, columns, rows):
                written.update({cluster_id: position for cluster_id, position in rows})

        onboarding.materialize(FakeClient(), [7, 9, 4])

        assert written == {7: 0, 9: 1, 4: 2}
