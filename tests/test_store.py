"""Tests for the D1 HTTP client used by the ingestion job.

The Worker reaches D1 through a binding. The ingestion job runs in GitHub
Actions, outside Cloudflare, so it goes through the HTTP API instead. Same
database, two doors.
"""

import pytest

from ingest.store import D1Client, D1Error, chunked


class FakeTransport:
    """Records calls and replays canned responses."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, json, headers):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return self.responses.pop(0)


def ok(results):
    return {"success": True, "result": [{"results": results, "meta": {"changes": len(results)}}]}


def client(transport):
    return D1Client(
        account_id="acct",
        database_id="db",
        api_token="segredo",
        post=transport,
    )


class TestQuery:
    def test_posts_to_the_d1_query_endpoint(self):
        transport = FakeTransport([ok([])])

        client(transport).query("SELECT 1")

        call = transport.calls[0]
        assert call["url"] == (
            "https://api.cloudflare.com/client/v4/accounts/acct/d1/database/db/query"
        )

    def test_sends_the_token_as_a_bearer_header(self):
        transport = FakeTransport([ok([])])

        client(transport).query("SELECT 1")

        assert transport.calls[0]["headers"]["Authorization"] == "Bearer segredo"

    def test_returns_the_rows_from_the_nested_envelope(self):
        rows = [{"id": 1, "title": "Copom mantem a Selic"}]
        transport = FakeTransport([ok(rows)])

        assert client(transport).query("SELECT id, title FROM articles") == rows

    def test_parameters_are_bound_not_interpolated(self):
        """String building here would be an injection hole and a cache miss."""
        transport = FakeTransport([ok([])])

        client(transport).query("SELECT * FROM articles WHERE url = ?", ["https://x.com/a"])

        assert transport.calls[0]["json"]["params"] == ["https://x.com/a"]
        assert "https://x.com/a" not in transport.calls[0]["json"]["sql"]

    def test_an_api_failure_raises_instead_of_returning_nothing(self):
        """A silent empty result would look like an empty corpus."""
        transport = FakeTransport([{"success": False, "errors": [{"message": "no such table"}]}])

        with pytest.raises(D1Error, match="no such table"):
            client(transport).query("SELECT * FROM missing")


class TestChunked:
    def test_splits_into_pieces_of_the_requested_size(self):
        assert list(chunked([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]

    def test_a_short_sequence_yields_one_chunk(self):
        assert list(chunked([1, 2], 10)) == [[1, 2]]

    def test_empty_input_yields_nothing(self):
        assert list(chunked([], 10)) == []


class TestInsertMany:
    def test_rows_are_sent_as_a_single_multi_row_insert(self):
        """One request per row would be thousands of round trips per run."""
        transport = FakeTransport([ok([])])

        client(transport).insert_many(
            "article_terms",
            ("article_id", "term", "tf"),
            [(1, "selic", 0.5), (1, "copom", 0.5)],
        )

        sent = transport.calls[0]["json"]
        assert sent["sql"].count("(?, ?, ?)") == 2
        assert sent["params"] == [1, "selic", 0.5, 1, "copom", 0.5]

    def test_large_batches_are_split_to_stay_under_the_bind_limit(self):
        """D1 allows 100 bound parameters per query, so 3 columns cap at 33 rows.

        Asserting the limit rather than a call count: if the chunk size is
        tuned later the test still guards the thing that actually breaks.
        """
        transport = FakeTransport([ok([])] * 50)
        rows = [(i, f"termo{i}", 0.1) for i in range(200)]

        client(transport).insert_many("article_terms", ("article_id", "term", "tf"), rows)

        assert len(transport.calls) > 1
        for call in transport.calls:
            assert len(call["json"]["params"]) <= 100
        assert sum(len(c["json"]["params"]) for c in transport.calls) == 600

    def test_no_rows_means_no_request(self):
        transport = FakeTransport([])

        client(transport).insert_many("article_terms", ("article_id", "term", "tf"), [])

        assert transport.calls == []
