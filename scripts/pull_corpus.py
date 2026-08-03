"""Takes the snapshot the simulator runs against.

Separate from the simulation itself because the two have different costs and
different lifetimes. Reading the window out of D1 is a few dozen round trips;
running a coordinate sweep over it is fifty simulations that touch no network at
all. Keeping them apart is what lets a sweep be re-run against exactly the corpus
the last one used, which is the only way two results are comparable.

    uv run --group ingest python -m scripts.pull_corpus
"""

from sim import corpus


def main() -> None:
    snapshot = corpus.load(refresh=True)

    print(
        f"{len(snapshot.cards)} clusters na janela, "
        f"{len(snapshot.document_counts)} termos, "
        f"{len(snapshot.edges)} termos com vizinhos, "
        f"corpus de {snapshot.total_docs} documentos"
    )


if __name__ == "__main__":
    main()
