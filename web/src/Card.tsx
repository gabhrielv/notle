import { useCallback, useEffect, useRef } from 'react'
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

/**
 * Accumulates how long the card was actually on screen, and reports once.
 *
 * Once per mount, not once per pass across the viewport: a reader scrolling up
 * and back down would otherwise spend a story's three impressions without ever
 * having been offered it three times.
 *
 * A skeleton card never reaches here, which is deliberate. Counting a
 * placeholder as an impression would record a view of a story nobody saw and
 * poison the repetition limit with a ghost.
 */
function useOnScreen(report: (visibleMs: number) => void) {
  const ref = useRef<HTMLLIElement | null>(null)
  const since = useRef<number | null>(null)
  const total = useRef(0)
  const done = useRef(false)

  useEffect(() => {
    const node = ref.current
    if (!node) return

    const settle = () => {
      if (since.current !== null) {
        total.current += Date.now() - since.current
        since.current = null
      }
      if (!done.current) {
        done.current = true
        report(total.current)
      }
    }

    const observer = new IntersectionObserver(
      (entries) => {
        const showing = entries[0]?.isIntersecting
        if (showing) {
          since.current ??= Date.now()
        } else if (since.current !== null) {
          settle()
        }
      },
      { threshold: 0.5 },
    )

    observer.observe(node)
    return () => {
      observer.disconnect()
      settle()
    }
  }, [report])

  return ref
}

type Props = {
  card: CardData
  index: number
  isLead: boolean
  leaving: boolean
  busy: boolean
  /**
   * False on an anonymous search, where the promise is that nothing is
   * recorded. The buttons are the only thing that records, so they are the
   * thing that goes.
   */
  canAct: boolean
  onAct: (cluster: number, type: Signal) => void
  onSeen: (cluster: number, visibleMs: number, textLength: number) => void
  onOpen: (cluster: number) => void
}

export function Card({
  card,
  index,
  isLead,
  leaving,
  busy,
  canAct,
  onAct,
  onSeen,
  onOpen,
}: Props) {
  // What the reader actually had in front of them, which is what a dwell is
  // normalized by. Headline plus summary, because both are rendered; counting
  // only the headline would say a card with three lines of text under it was
  // read as fast as one without.
  const shown = card.title.length + card.summary.length
  const report = useCallback(
    (visibleMs: number) => onSeen(card.cluster_id, visibleMs, shown),
    [onSeen, card.cluster_id, shown],
  )
  const ref = useOnScreen(report)

  const others = card.also_in
  // Beyond the anchor's own article, the rest of a single portal cluster is the
  // same template repeated per city. Counting them is honest; listing the
  // portal against itself is not.
  const repeats = card.size - 1

  return (
    <li
      ref={ref}
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
      {(card.about.length > 0 || card.discovery) && (
        <p className="kicker">
          {card.discovery && <span className="badge">descoberta</span>}
          {card.about.slice(0, 3).join(' · ')}
        </p>
      )}

      <h2 className="headline">
        <a
          href={card.url}
          target="_blank"
          rel="noopener noreferrer"
          onClick={() => onOpen(card.cluster_id)}
        >
          {card.title}
        </a>
      </h2>

      {card.summary && <p className="summary">{card.summary}</p>}

      <p className="byline">
        <b>{card.source}</b> · {sayAge(card.published_at)}
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

      {canAct && (
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
      )}
    </li>
  )
}
