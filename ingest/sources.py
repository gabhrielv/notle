"""The feeds the corpus is built from.

Six portals across different editorial lines. Two reasons for the spread: TF-IDF
only says something useful when the vocabulary varies, and slice 2 has nothing
to deduplicate unless several portals cover the same event.

Agencia Brasil is public and permissively licensed, which makes it the safe
floor if any commercial feed ever has to be dropped.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Source:
    name: str
    feed_url: str
    homepage_url: str


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
)
