import { useCallback, useEffect, useRef } from 'react'
import type { Card as CardData, Signal } from './api'
import { sayAge } from './api'

/**
 * How many portals ran the story, as a number in the left gutter.
 *
 * A drawn symbol was tried first and failed at the only job it had: a reader
 * cannot tell three rings from four without stopping to count them, and the
 * whole point of putting this in the gutter is that it reads at a glance while
 * scrolling. The digit says it outright, and the accent ring separates the one
 * case that matters, which is several portals landing on the same event.
 *
 * The rule below it joins the counters into a continuous line down the list, so
 * the column reads as a scale rather than as a stack of loose badges.
 */
function Mark({ plates }: { plates: number }) {
  return (
    <>
      <span
        className={`mark${plates > 1 ? ' is-many' : ''}`}
        aria-label={`${plates} ${plates === 1 ? 'portal' : 'portais'}`}
      >
        {plates}
      </span>
      <span className="spine" aria-hidden="true" />
    </>
  )
}

/** Inline rather than an icon font, because the app has to render offline. */
function IconKeep() {
  return (
    <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M8 3v10M3 8h10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  )
}

function IconHide() {
  return (
    <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path
        d="M2 8s2.4-4 6-4 6 4 6 4-2.4 4-6 4-6-4-6-4Z"
        stroke="currentColor"
        strokeWidth="1.4"
      />
      <path d="M3 13 13 3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
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

  const hasRegister = others.length > 0 || repeats > 0
  const hasReasons = card.because.length > 0 || card.against.length > 0

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

      {/* One panel, because "also in" and the two reasons answer a single
          question: why is this card here. Left loose at the foot of the card
          they read as trailing grey metadata, which is the one treatment the
          explanation cannot have in this product. */}
      {(hasRegister || hasReasons) && (
        <div className="meta">
          {others.length > 0 ? (
            <div className="register">
              <span className="register-label">também em</span>
              {others.map((name) => (
                <span key={name} className="plate">
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

          {/* The terms come from the same aggregation that produced the score,
              so this is the arithmetic of the position rather than a
              description written next to it. */}
          {hasReasons && (
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
        </div>
      )}

      {canAct && (
        <div className="actions">
          <button
            type="button"
            className="action is-keep"
            disabled={busy}
            onClick={() => onAct(card.cluster_id, 'like')}
          >
            <IconKeep />
            Interessa
          </button>
          <button
            type="button"
            className="action"
            disabled={busy}
            onClick={() => onAct(card.cluster_id, 'hide')}
          >
            <IconHide />
            Ocultar
          </button>
        </div>
      )}
    </li>
  )
}
