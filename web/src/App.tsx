import { useCallback, useEffect, useState } from 'react'
import { Card } from './Card'
import { readFeed, record } from './api'
import type { Feed, Signal } from './api'

/**
 * Below this the skeleton is worse than nothing: it paints and clears inside
 * one frame or two, which reads as a flicker rather than as progress.
 */
const SKELETON_AFTER_MS = 200

/** Long enough for the card to finish leaving before it stops existing. */
const LEAVE_MS = 240

/** The masthead line, naming both halves of the profile once each exists. */
function describeProfile(profile: Feed['profile']): string {
  const kept = profile.empty ? '' : `${profile.terms} termos de gosto`
  const hidden = profile.hidden_terms ? `${profile.hidden_terms} termos escondidos` : ''

  if (kept && hidden) return `${kept}, ${profile.hidden_terms} escondidos`
  return kept || hidden || 'feed ainda sem gosto registrado'
}

function Skeleton() {
  return (
    <ul className="feed">
      {[0, 1, 2, 3].map((i) => (
        <li key={i} className="card" style={{ '--i': i } as React.CSSProperties}>
          <div className="gutter" />
          <div>
            <div className="bone bone-kicker" />
            <div className="bone bone-line" />
            <div className="bone bone-line is-short" />
            <div className="bone bone-meta" />
          </div>
        </li>
      ))}
    </ul>
  )
}

export default function App() {
  const [data, setData] = useState<Feed | null>(null)
  const [failed, setFailed] = useState(false)
  const [slow, setSlow] = useState(false)
  const [leaving, setLeaving] = useState<number[]>([])
  const [busy, setBusy] = useState<number | null>(null)
  const [problem, setProblem] = useState<string | null>(null)

  const load = useCallback(() => {
    const controller = new AbortController()

    setData(null)
    setFailed(false)
    setSlow(false)
    setLeaving([])
    const timer = setTimeout(() => setSlow(true), SKELETON_AFTER_MS)

    readFeed(controller.signal)
      .then(setData)
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setFailed(true)
        void error
      })
      .finally(() => clearTimeout(timer))

    return () => {
      controller.abort()
      clearTimeout(timer)
    }
  }, [])

  useEffect(load, [load])

  async function act(cluster: number, type: Signal) {
    setBusy(cluster)
    setProblem(null)
    try {
      await record(cluster, type)
      setLeaving((current) => [...current, cluster])
      setTimeout(() => {
        setData((current) =>
          current
            ? { ...current, feed: current.feed.filter((c) => c.cluster_id !== cluster) }
            : current,
        )
      }, LEAVE_MS)
    } catch {
      setProblem('Não deu para registrar. A matéria segue na lista.')
    } finally {
      setBusy(null)
    }
  }

  const cards = data?.feed ?? []
  // Anything the reader answers for leaves the whole response on the next load,
  // so this list only needs to survive until then.
  const held = data?.held_back ?? []

  return (
    <main className="shell">
      <header className="masthead">
        <h1 className="wordmark">
          Notle<span>.</span>
        </h1>
        <p className="standfirst">
          {data ? describeProfile(data.profile) : 'lendo a janela'}
        </p>
      </header>

      {problem && <p className="hint">{problem}</p>}

      {data?.user.is_new && cards.length > 0 && (
        <p className="hint">
          Interessa e ocultar ensinam o feed. A matéria sai da lista e o próximo carregamento
          já leva em conta o que você marcou.
        </p>
      )}

      {!data && !failed && slow && <Skeleton />}

      {cards.length > 0 && (
        <ul className="feed">
          {cards.map((card, i) => (
            <Card
              key={card.cluster_id}
              card={card}
              index={i}
              isLead={i === 0}
              leaving={leaving.includes(card.cluster_id)}
              busy={busy === card.cluster_id}
              onAct={act}
            />
          ))}
        </ul>
      )}

      {held.length > 0 && (
        <section className="held">
          <h2 className="held-title">O que você afastou</h2>
          <p className="held-body">
            {held.length === 1
              ? 'Uma matéria desta janela desceu'
              : `${held.length} matérias desta janela desceram`}{' '}
            porque se parecem com o que você escondeu. Elas ficaram fora do feed acima.
          </p>
          <ul className="held-list">
            {held.map((card) => (
              <li key={card.cluster_id} className="held-item">
                <a
                  className="held-link"
                  href={card.url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {card.title}
                </a>
                <p className="held-meta">
                  <span className="held-terms">↓ {card.against.join(' · ')}</span>
                  <span>{card.source}</span>
                </p>
              </li>
            ))}
          </ul>
        </section>
      )}

      {failed && (
        <section className="notice">
          <h2 className="notice-title">O feed não carregou</h2>
          <p className="notice-body">
            A chamada para a API não voltou. Pode ser a rede ou o banco.
          </p>
          <button type="button" className="action" onClick={load}>
            Tentar de novo
          </button>
        </section>
      )}

      {data && cards.length === 0 && (
        <section className="notice">
          <h2 className="notice-title">Nada na janela agora</h2>
          <p className="notice-body">
            A ingestão lê os portais de hora em hora, e o feed só considera as últimas 48
            horas. Se você acabou de responder a tudo, volte depois da próxima passada.
          </p>
          <button type="button" className="action" onClick={load}>
            Recarregar
          </button>
        </section>
      )}
    </main>
  )
}
