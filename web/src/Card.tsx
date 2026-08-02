import type { Card as CardData, Signal } from './api'
import { sayAge } from './api'

/**
 * A printer's registration mark, one ring per portal that ran the story.
 *
 * The extra rings sit off centre on purpose. Misregistration is what a press
 * produces when plates do not line up, and several portals landing on one event
 * is exactly the thing this feed is built to show.
 */
function Mark({ plates }: { plates: number }) {
  const offsets = [
    [1.8, -1.4],
    [-1.6, 1.5],
  ]
  const extra = Math.min(plates - 1, offsets.length)

  return (
    <svg className="mark" viewBox="0 0 26 26" width="26" height="26" aria-hidden="true">
      {Array.from({ length: extra }, (_, i) => (
        <circle
          key={i}
          cx={13 + offsets[i][0]}
          cy={13 + offsets[i][1]}
          r="7"
          fill="none"
          stroke="var(--reg)"
          strokeWidth="1"
          opacity="0.8"
        />
      ))}
      <circle cx="13" cy="13" r="7" fill="none" stroke="currentColor" strokeWidth="1" />
      <path
        d="M13 1.5v4M13 20.5v4M1.5 13h4M20.5 13h4"
        stroke="currentColor"
        strokeWidth="1"
      />
    </svg>
  )
}

type Props = {
  card: CardData
  index: number
  isLead: boolean
  leaving: boolean
  busy: boolean
  onAct: (cluster: number, type: Signal) => void
}

export function Card({ card, index, isLead, leaving, busy, onAct }: Props) {
  const others = card.also_in
  // Beyond the anchor's own article, the rest of a single portal cluster is the
  // same template repeated per city. Counting them is honest; listing the
  // portal against itself is not.
  const repeats = card.size - 1

  return (
    <li
      className={`card${isLead ? ' is-lead' : ''}${leaving ? ' is-leaving' : ''}`}
      // The stagger stops counting after a handful of cards. Left uncapped, a
      // full page would hold the last one back by more than a second, and a
      // reveal that outlasts the reader's patience is just a delay.
      style={{ '--i': Math.min(index, 7) } as React.CSSProperties}
    >
      <div className="gutter">
        <Mark plates={others.length + 1} />
      </div>

      {/* The cluster's own strongest terms, not an editorial section. One term
          alone reads as a category and gets it wrong, because the strongest term
          by IDF is whichever proper noun is rarest: a story about a candidate
          comes back labelled with the park he spoke in. Three terms describe the
          group instead of miscalling it. */}
      {card.about.length > 0 && (
        <p className="kicker">{card.about.slice(0, 3).join(' · ')}</p>
      )}

      <h2 className="headline">
        <a href={card.url} target="_blank" rel="noopener noreferrer">
          {card.title}
        </a>
      </h2>

      <p className="byline">
        <b>{card.source}</b> · {sayAge(card.age_hours)}
      </p>

      {others.length > 0 ? (
        <div className="register">
          <span className="register-label">também em</span>
          {others.map((name, i) => (
            <span
              key={name}
              className="plate"
              style={
                {
                  '--p': i,
                  '--dx': `${i % 2 === 0 ? 5 : -4}px`,
                  '--dy': `${i % 2 === 0 ? -3 : 4}px`,
                } as React.CSSProperties
              }
            >
              {name}
            </span>
          ))}
        </div>
      ) : (
        repeats > 0 && (
          <div className="register">
            <span className="tally">
              mais {repeats} {repeats === 1 ? 'matéria' : 'matérias'} no {card.source}
            </span>
          </div>
        )
      )}

      {/* Why this card sits where it does, in both directions and only when
          there is something to say. The terms come from the same aggregation
          that produced the score, so this is the arithmetic of the position
          rather than a description written next to it. */}
      {(card.because.length > 0 || card.against.length > 0) && (
        <dl className="reasons">
          {card.because.length > 0 && (
            <div className="reason">
              <dt className="reason-label">porque você acompanha</dt>
              <dd className="reason-terms">{card.because.join(' · ')}</dd>
            </div>
          )}
          {card.against.length > 0 && (
            <div className="reason is-against">
              <dt className="reason-label">porque você escondeu</dt>
              <dd className="reason-terms">{card.against.join(' · ')}</dd>
            </div>
          )}
        </dl>
      )}

      <div className="actions">
        <button
          type="button"
          className="action is-keep"
          disabled={busy}
          onClick={() => onAct(card.cluster_id, 'like')}
        >
          Interessa
        </button>
        <button
          type="button"
          className="action"
          disabled={busy}
          onClick={() => onAct(card.cluster_id, 'hide')}
        >
          Ocultar
        </button>
      </div>
    </li>
  )
}
