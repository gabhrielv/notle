"""The feeds the corpus is built from.

Two groups, and the split is deliberate. The first six are general Brazilian
portals across different editorial lines: TF-IDF only says something useful when
the vocabulary varies, and clustering has nothing to deduplicate unless several
portals cover the same event.

The rest are the technology and AI press, which the general portals cover
thinly and late. They are what makes a search for a subject return the subject
rather than the two days a year it reached the front page.

Four of those publish in English, and that is why `Source` carries a language.
It is not a label: it selects the spaCy model and the discard list together in
`normalize`, and running the wrong one is not a small loss of quality. The
Portuguese model reads English `build` as `buildr` and leaves `model` and
`models` as two terms that never meet, which is the exact failure lemmatisation
exists to prevent.

The two languages share one corpus and one IDF, and they do not cluster with
each other, because a Portuguese and an English article about one event have
almost no vocabulary in common. That is the correct outcome rather than a
limitation to work around: they are different articles for different readers,
and the card that groups them would be claiming a sameness the vectors do not
show.

Agencia Brasil is public and permissively licensed, which makes it the safe
floor if any commercial feed ever has to be dropped.

Every feed here was checked before being added, for three things at once: that
it answers, how many items it carries, and how old its newest story is. Several
obvious names failed that check and are not here. Tecmundo's documented feed
returns zero items and only the `rss.` host works. Gizmodo Brasil and the Verge's
section feed refuse the request outright. VentureBeat's AI feed answers with
seven items whose newest is seventy five days old, which is a dead feed serving
200. Meio Bit and Startups were both over two days stale when tested.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Source:
    name: str
    feed_url: str
    homepage_url: str
    language: str = "pt"


def portal_names() -> frozenset[str]:
    """The portals' own names, lowercased, as terms never to keep.

    A portal names itself inside its own summaries, so entity recognition turns
    it into a term and it enters the feature space. `olhar digital` reached the
    strongest terms of a simulated reader's profile that way, which is the
    publisher leaking into a vector that is supposed to be about subjects.

    Structural rather than a curated list: it is derived from `SOURCES`, so
    adding a feed adds its name here and removing one removes it, with nothing
    to remember.
    """
    return frozenset(source.name.lower() for source in SOURCES)


SOURCES = (
    Source("G1", "https://g1.globo.com/rss/g1/", "https://g1.globo.com"),
    Source(
        "Folha de S.Paulo",
        "https://feeds.folha.uol.com.br/emcimadahora/rss091.xml",
        "https://www.folha.uol.com.br",
    ),
    Source(
        "BBC News Brasil",
        "https://feeds.bbci.co.uk/portuguese/rss.xml",
        "https://www.bbc.com/portuguese",
    ),
    Source("CNN Brasil", "https://www.cnnbrasil.com.br/feed/", "https://www.cnnbrasil.com.br"),
    Source(
        "Agencia Brasil",
        "https://agenciabrasil.ebc.com.br/rss/ultimasnoticias/feed.xml",
        "https://agenciabrasil.ebc.com.br",
    ),
    Source("Poder360", "https://www.poder360.com.br/feed/", "https://www.poder360.com.br"),
    # Technology and AI, in Portuguese.
    Source("Tecnoblog", "https://tecnoblog.net/feed/", "https://tecnoblog.net"),
    Source("Canaltech", "https://canaltech.com.br/rss/", "https://canaltech.com.br"),
    Source(
        "Olhar Digital",
        "https://olhardigital.com.br/feed/",
        "https://olhardigital.com.br",
    ),
    # Technology and AI, in English.
    Source(
        "The Verge",
        "https://www.theverge.com/rss/index.xml",
        "https://www.theverge.com",
        language="en",
    ),
    Source(
        "TechCrunch",
        "https://techcrunch.com/feed/",
        "https://techcrunch.com",
        language="en",
    ),
    Source(
        "MIT Technology Review",
        "https://www.technologyreview.com/feed/",
        "https://www.technologyreview.com",
        language="en",
    ),
    Source(
        "IEEE Spectrum",
        "https://spectrum.ieee.org/feeds/topic/artificial-intelligence.rss",
        "https://spectrum.ieee.org",
        language="en",
    ),
    Source("Tecmundo", "https://rss.tecmundo.com.br/feed", "https://www.tecmundo.com.br"),
    Source("Adrenaline", "https://www.adrenaline.com.br/feed/", "https://www.adrenaline.com.br"),
    Source(
        "Hardware.com.br",
        "https://www.hardware.com.br/feed/",
        "https://www.hardware.com.br",
    ),
    Source(
        "MIT Technology Review Brasil",
        "https://mittechreview.com.br/feed/",
        "https://mittechreview.com.br",
    ),
    Source(
        "The Register",
        "https://www.theregister.com/headlines.atom",
        "https://www.theregister.com",
        language="en",
    ),
    Source(
        "Engadget",
        "https://www.engadget.com/rss.xml",
        "https://www.engadget.com",
        language="en",
    ),
    Source("Wired", "https://www.wired.com/feed/rss", "https://www.wired.com", language="en"),
)
