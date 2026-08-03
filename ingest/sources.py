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

The last group is the international press, and it is picked for the place it
reports from rather than for how much it publishes. Rest of World covers
technology outside the countries that usually get covered, the South China
Morning Post covers Asia, and the Guardian and BBC technology desks are general
newsrooms rather than trade press, which is a different editorial line from every
other English feed here. Ars Technica and Tom's Hardware go deeper than the rest
on the technical side, and ZDNET covers the enterprise nobody else does.

Names that already have a voice here were left out on purpose. Gizmodo,
TechRadar, Digital Trends and Wired UK all answered and all were fresh, and all
four repeat what Engadget, the Verge and Wired already say.

Every feed here was checked before being added, for three things at once: that
it answers, how many items it carries, and how old its newest story is. Several
obvious names failed that check and are not here. Tecmundo's documented feed
returns zero items and only the `rss.` host works. Gizmodo Brasil and the Verge's
section feed refuse the request outright. VentureBeat's AI feed answers with
seven items whose newest is seventy five days old, which is a dead feed serving
200. Meio Bit and Startups were both over two days stale when tested. DW Brasil
and El Pais Brasil answer with dozens of items dated more than three years back.
MIT News was four days stale. Nikkei Asia carries no dates at all, which makes
every story undatable and therefore unrankable by recency.
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
    # The international press, chosen for where they report from rather than for
    # how much they publish. The block above is almost entirely American trade
    # coverage, so adding more of it would have deepened one voice instead of
    # widening the corpus.
    Source(
        "Ars Technica",
        "https://feeds.arstechnica.com/arstechnica/index",
        "https://arstechnica.com",
        language="en",
    ),
    Source(
        "Rest of World",
        "https://restofworld.org/feed/latest",
        "https://restofworld.org",
        language="en",
    ),
    Source(
        "South China Morning Post",
        "https://www.scmp.com/rss/36/feed",
        "https://www.scmp.com",
        language="en",
    ),
    Source(
        "The Guardian",
        "https://www.theguardian.com/uk/technology/rss",
        "https://www.theguardian.com/technology",
        language="en",
    ),
    Source(
        "BBC Technology",
        "https://feeds.bbci.co.uk/news/technology/rss.xml",
        "https://www.bbc.com/news/technology",
        language="en",
    ),
    Source(
        "Tom's Hardware",
        "https://www.tomshardware.com/feeds/all",
        "https://www.tomshardware.com",
        language="en",
    ),
    Source("ZDNET", "https://www.zdnet.com/news/rss.xml", "https://www.zdnet.com", language="en"),
    # Beats nobody here covered. Security and research were blind spots: the
    # corpus could not answer a question about a breach or a paper except through
    # whatever the consumer press happened to repeat.
    Source(
        "The Hacker News",
        "https://feeds.feedburner.com/TheHackersNews",
        "https://thehackernews.com",
        language="en",
    ),
    Source(
        "BleepingComputer",
        "https://www.bleepingcomputer.com/feed/",
        "https://www.bleepingcomputer.com",
        language="en",
    ),
    Source("Nature", "https://www.nature.com/nature.rss", "https://www.nature.com", language="en"),
    Source(
        "Phys.org",
        "https://phys.org/rss-feed/technology-news/",
        "https://phys.org",
        language="en",
    ),
    Source(
        "New Scientist",
        "https://www.newscientist.com/feed/home/",
        "https://www.newscientist.com",
        language="en",
    ),
    Source(
        "Quanta Magazine",
        "https://api.quantamagazine.org/feed/",
        "https://www.quantamagazine.org",
        language="en",
    ),
    Source("InfoQ", "https://feed.infoq.com/", "https://www.infoq.com", language="en"),
    Source(
        "CNBC Technology",
        "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=19854910",
        "https://www.cnbc.com/technology",
        language="en",
    ),
    # Consumer coverage. It overlaps the desks above by design: the ask was for
    # more English, and this is where the English volume is.
    Source("9to5Mac", "https://9to5mac.com/feed/", "https://9to5mac.com", language="en"),
    Source("TechRadar", "https://www.techradar.com/rss", "https://www.techradar.com", language="en"),
    Source(
        "MacRumors",
        "https://feeds.macrumors.com/MacRumors-All",
        "https://www.macrumors.com",
        language="en",
    ),
    Source(
        "Digital Trends",
        "https://www.digitaltrends.com/feed/",
        "https://www.digitaltrends.com",
        language="en",
    ),
    Source(
        "XDA Developers",
        "https://www.xda-developers.com/feed/",
        "https://www.xda-developers.com",
        language="en",
    ),
    Source("Gizmodo", "https://gizmodo.com/rss", "https://gizmodo.com", language="en"),
    Source("404 Media", "https://www.404media.co/rss/", "https://www.404media.co", language="en"),
    Source(
        "NPR Technology",
        "https://feeds.npr.org/1019/rss.xml",
        "https://www.npr.org/sections/technology",
        language="en",
    ),
    # Aggregators, and they are a different kind of thing from everything above.
    # They do not publish the story, they point at it, so a card that groups one
    # of them with the portals will say they covered something they only linked.
    # Added deliberately with that understood.
    Source(
        "Hacker News (YC)",
        "https://hnrss.org/frontpage",
        "https://news.ycombinator.com",
        language="en",
    ),
    Source(
        "Slashdot",
        "https://rss.slashdot.org/Slashdot/slashdotMain",
        "https://slashdot.org",
        language="en",
    ),
)
