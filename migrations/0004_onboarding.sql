-- Slice 4: the screen most visitors will only ever see.
--
-- Every visitor is anonymous, so every visitor is a cold start, and until now
-- the first screen was ordered by nothing but the clock. This is what seeds a
-- profile before the reader has done anything at all.

-- The twelve headlines the onboarding offers, chosen by the ingestion job.
--
-- Materialized rather than picked per request, and the reason is the same one
-- that put IDF and clustering in the job. Variety is not the twelve most recent
-- stories: the top of the window is routinely a run of the same local crime
-- report from one portal. Getting variety means comparing each candidate
-- against the ones already chosen, which is a few thousand cosines, and the
-- architecture's line is that nothing heavy happens inside a request. Least of
-- all inside this one, which is the request that decides whether a visitor
-- stays.
--
-- Replaced wholesale on every run, exactly like `feed_candidates`, because the
-- window slides and most of what changes is which rows belong at all.
CREATE TABLE onboarding_picks (
    cluster_id INTEGER PRIMARY KEY REFERENCES clusters(id),
    position   INTEGER NOT NULL
);

CREATE INDEX idx_onboarding_position ON onboarding_picks(position);

-- When the reader answered the onboarding, either by choosing or by skipping.
--
-- A column rather than inferring it from an empty profile. Inferring fails in
-- both directions: someone who skipped would be asked again on every visit, and
-- someone who chose and later hid everything would be dropped back into the
-- form with no idea why.
ALTER TABLE users ADD COLUMN onboarded_at TEXT;
