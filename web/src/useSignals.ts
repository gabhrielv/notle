import { useCallback, useEffect, useRef } from 'react'
import { sendSignals } from './api'
import { sessionId } from './session'
import { makeQueue } from './signalQueue'
import type { SignalEvent } from './api'

/** How long a batch may sit before it goes, so a quiet reader is still recorded. */
const FLUSH_EVERY_MS = 8000

/**
 * Below this a card was scrolled past, not looked at. Without a floor, flinging
 * down a page would report thirty impressions and thirty dwells, and the feed
 * would stop offering stories nobody saw.
 */
const SEEN_FOR_MS = 1000

/**
 * One session's worth of implicit measurement.
 *
 * Everything here is a guess about intent read off a browser event, which is why
 * none of it carries a value: the client says what happened and for how long,
 * and the server decides what that is worth. A browser allowed to report its own
 * weights would be a browser writing into someone's taste profile.
 *
 * Nothing is sent at all when `active` is false. That is the anonymous search
 * promise, kept where it can be seen rather than in a flag the server has to
 * honour.
 */
export function useSignals(active: boolean) {
  const session = useRef(sessionId())
  const queue = useRef(
    makeQueue((events, beacon) => sendSignals(session.current, events, beacon)),
  )
  // What the reader clicked through to, and when. Kept in a ref because the
  // answer arrives in a visibility event that has no idea a click happened.
  const away = useRef<{ cluster: number; left: number } | null>(null)

  const flush = useCallback((beacon = false) => queue.current.flush(beacon), [])

  const push = useCallback(
    (event: SignalEvent) => {
      if (!active) return
      queue.current.push(event)
    },
    [active],
  )

  useEffect(() => {
    if (!active) return

    const timer = setInterval(() => flush(), FLUSH_EVERY_MS)

    // pagehide rather than unload: unload is ignored on mobile Safari and blocks
    // the back forward cache everywhere else, so the last batch of a session
    // would be the one most often lost.
    const onHide = () => flush(true)
    window.addEventListener('pagehide', onHide)

    return () => {
      clearInterval(timer)
      window.removeEventListener('pagehide', onHide)
      flush(true)
    }
  }, [active, flush])

  /** The tab going dark and coming back is how time spent away is measured. */
  useEffect(() => {
    if (!active) return

    const onVisibility = () => {
      const pending = away.current
      if (document.visibilityState === 'hidden') {
        // The batch may not survive the tab being frozen, so it goes now.
        flush(true)
        return
      }
      if (!pending) return

      away.current = null
      push({
        type: 'return',
        cluster_id: pending.cluster,
        duration_ms: Date.now() - pending.left,
      })
    }

    document.addEventListener('visibilitychange', onVisibility)
    return () => document.removeEventListener('visibilitychange', onVisibility)
  }, [active, flush, push])

  const clicked = useCallback(
    (cluster: number) => {
      push({ type: 'click', cluster_id: cluster })
      // The link opens a tab, so this one goes hidden in a moment and the clock
      // starts there. Recorded now because the visibility event cannot know
      // which card sent the reader away.
      away.current = { cluster, left: Date.now() }
    },
    [push],
  )

  const seen = useCallback(
    (cluster: number, visibleMs: number, textLength: number) => {
      if (visibleMs < SEEN_FOR_MS) return

      push({ type: 'impression', cluster_id: cluster })
      push({
        type: 'dwell',
        cluster_id: cluster,
        duration_ms: visibleMs,
        text_length: textLength,
      })
    },
    [push],
  )

  return { seen, clicked, flush }
}
