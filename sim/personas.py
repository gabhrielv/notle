"""Readers with a taste the ranking cannot see.

The architecture registers the objection that makes this whole exercise fragile:
a simulator is only worth anything if the persona's behaviour is independent of
the formula being evaluated. If the persona likes exactly what the algorithm
predicts, the experiment proves the system agrees with itself.

So a persona's truth is the portal that published the story. The ranking never
sees `source_id`: it does not enter a vector, a cosine, an IDF or the decay, and
nothing downstream of `article_terms` knows a story came from IEEE Spectrum
rather than from G1. That makes the ground truth genuinely disjoint from the
feature space, and turns the question into the one worth asking: does keeping a
technology story make the system surface another technology story, given that it
has never been told what technology means?

The behaviour model is deliberately crude, for the same reason. A persona reads
the page it is given, keeps what is on its subject and hides what is furthest
from it. It does not consult a cosine, a score, or anything the ranker computed.
"""

from dataclasses import dataclass

# How much of what a persona is offered it bothers to answer.
#
# A reader who likes every matching story on every page converges in one round
# and tells us nothing about the shape of the curve. Three keeps and one hide is
# closer to a real session and slow enough that the rounds are distinguishable.
KEEPS_PER_ROUND = 3
HIDES_PER_ROUND = 1


@dataclass(frozen=True)
class Persona:
    name: str
    # Portals whose stories this reader considers on-subject. The one thing the
    # ranking is never allowed to know.
    sources: frozenset[str]

    def likes(self, card) -> bool:
        return card["source"] in self.sources


TECH = Persona(
    name="tecnologia",
    sources=frozenset(
        {
            "Tecnoblog",
            "Canaltech",
            "Olhar Digital",
            "The Verge",
            "TechCrunch",
            "MIT Technology Review",
            "IEEE Spectrum",
        }
    ),
)

POLITICS = Persona(name="politica", sources=frozenset({"Poder360"}))

PERSONAS = (TECH, POLITICS)


def answer(persona: Persona, page: list[dict]) -> tuple[list[int], list[int]]:
    """What this reader does with a page, in cluster ids.

    Keeps come from the top of the page rather than from the best matches,
    because a reader answers what is in front of them. Hides come from the
    bottom, which is the crudest possible stand-in for "furthest from what I
    want" that does not consult the ranking's own opinion.
    """
    on_subject = [card["cluster_id"] for card in page if persona.likes(card)]
    off_subject = [card["cluster_id"] for card in page if not persona.likes(card)]

    return on_subject[:KEEPS_PER_ROUND], off_subject[-HIDES_PER_ROUND:]
