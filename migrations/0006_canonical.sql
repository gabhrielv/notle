-- The term each written word reduces to, decided by the corpus rather than by
-- the tagger's reading of one sentence.
--
-- spaCy reads the same word differently at the head of a sentence than inside
-- one, because the capital there is forced by position and carries no
-- information. Brazilian headlines lead with the subject, so this lands on the
-- names the feed is about: `Petrobras anuncia` tags as a common noun and
-- lemmatizes to `petrobra`, while `da Petrobras` mid sentence stays
-- `petrobras`. The corpus then holds two terms for one company, each with half
-- the mass and an inflated IDF, and they never match each other.
--
-- Keyed by the written word and not by the term, and that is the safety of it.
-- A map from term to term merges words that were never the same word on the
-- page: measured over the headline corpus, a lemma-keyed version read `santo`
-- once out of seven occurrences of the surface `santos` and proposed rewriting
-- every saint in the archive into the football club. Keyed by surface, `santo`
-- and `santos` are different keys and hold separate votes, and the same
-- protection covers `deu` against `deus` without either being named anywhere.
--
-- Written by `reprocess_terms`, which is the only job that reads the whole
-- archive and can therefore count the readings. The hourly ingestion reads it
-- once per pass and applies it, so the corpus stops splitting between two
-- reprocessing runs instead of drifting back a few thousand articles at a time.
--
-- No index beyond the key: every reader wants the whole table and loads it into
-- a dictionary once.
CREATE TABLE term_canonical (
    surface   TEXT PRIMARY KEY,
    canonical TEXT NOT NULL
);
