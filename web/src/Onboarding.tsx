import { useState } from 'react'
import type { Card } from './api'
import { sayAge } from './api'

type Props = {
  offer: Card[]
  picks: number
  onDone: (picks: number[]) => Promise<void>
}

/**
 * The screen that decides whether a visitor stays.
 *
 * Every visitor is anonymous, so every one of them arrives here, and this is not
 * a form standing between them and the product: it is made of the product. The
 * twelve are real headlines from the last day, so reading them is already the
 * thing the site does.
 *
 * Skipping is offered as plainly as choosing. A screen that will not take no for
 * an answer teaches the reader that the close button is the way out.
 */
export function Onboarding({ offer, picks, onDone }: Props) {
  const [chosen, setChosen] = useState<number[]>([])
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)

  const full = chosen.length >= picks

  function toggle(cluster: number) {
    setChosen((current) =>
      current.includes(cluster)
        ? current.filter((id) => id !== cluster)
        : full
          ? current
          : [...current, cluster],
    )
  }

  async function finish(selection: number[]) {
    setBusy(true)
    setProblem(null)
    try {
      await onDone(selection)
    } catch {
      setProblem('Não deu para gravar. Tente de novo.')
      setBusy(false)
    }
  }

  return (
    <section className="onboard">
      <h1 className="onboard-title">
        Escolha três que você<span> leria</span>
      </h1>
      <p className="onboard-body">
        São manchetes de verdade das últimas 24 horas, escolhidas para cobrir
        assuntos diferentes. O que você marcar vira o ponto de partida do seu
        feed, e cada card depois diz por que está na posição em que está.
      </p>

      {problem && <p className="hint">{problem}</p>}

      <ul className="offer">
        {offer.map((card, i) => {
          const picked = chosen.includes(card.cluster_id)
          return (
            <li key={card.cluster_id}>
              <button
                type="button"
                className={`option${picked ? ' is-picked' : ''}`}
                aria-pressed={picked}
                disabled={busy || (full && !picked)}
                onClick={() => toggle(card.cluster_id)}
                style={{ '--i': Math.min(i, 11) } as React.CSSProperties}
              >
                {card.about.length > 0 && (
                  <span className="option-kicker">
                    {card.about.slice(0, 2).join(' · ')}
                  </span>
                )}
                <span className="option-title">{card.title}</span>
                <span className="option-meta">
                  {card.source}
                  {card.also_in.length > 0 && ` e mais ${card.also_in.length}`} ·{' '}
                  {sayAge(card.published_at)}
                </span>
              </button>
            </li>
          )
        })}
      </ul>

      <div className="onboard-actions">
        <button
          type="button"
          className="action is-keep"
          disabled={busy || chosen.length === 0}
          onClick={() => finish(chosen)}
        >
          {chosen.length === 0
            ? `Escolha ${picks}`
            : `Começar com ${chosen.length} de ${picks}`}
        </button>
        <button
          type="button"
          className="action is-quiet"
          disabled={busy}
          onClick={() => finish([])}
        >
          Pular e ver o feed
        </button>
      </div>
    </section>
  )
}
