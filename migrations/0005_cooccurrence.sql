-- Slice 7: which terms travel together.
--
-- The architecture's data model has listed this table since the beginning and no
-- migration ever created it, because nothing read it until now.
--
-- This is what stands in for collaborative filtering, which is blocked here
-- twice over: anonymous visitors on a demo mean a user/item matrix over 99%
-- empty, and news dies in 48 hours while item-item co-occurrence needs time to
-- accumulate. The corpus is the population instead, so a profile built on
-- `selic` can reach `cambio` without any crowd existing.
--
-- Both directions of every pair are stored. The index is on `term_a` alone, so a
-- profile holding either side has to find the other by looking up its own term;
-- storing one direction would make expansion depend on alphabetical order.
CREATE TABLE term_cooccur (
    term_a TEXT NOT NULL,
    term_b TEXT NOT NULL,
    score  REAL NOT NULL,
    PRIMARY KEY (term_a, term_b)
);

CREATE INDEX idx_term_cooccur_a ON term_cooccur(term_a);
