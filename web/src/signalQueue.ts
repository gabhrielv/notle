import type { SignalEvent } from './api'

/** Past this the queue goes early, rather than growing with a long scroll. */
export const FLUSH_AT = 20

/** How a batch actually leaves. Injected so the queue can be tested alone. */
export type Send = (events: SignalEvent[], beacon: boolean) => Promise<void> | void

/**
 * Holds measured events until something despatches them.
 *
 * A plain factory rather than state inside the hook, because the pull gesture
 * needs to await a despatch, and a queue living in a `useRef` can be reached
 * neither from outside React nor from a test.
 *
 * The batch is taken out of the queue before it is sent, not after. Clearing on
 * success instead would send an event twice whenever one despatch overlapped
 * the next, and these events are counted rather than merged: a doubled
 * impression is a story pushed out of the feed one viewing early.
 */
export function makeQueue(send: Send) {
  let events: SignalEvent[] = []

  async function flush(beacon = false): Promise<void> {
    if (!events.length) return

    const batch = events
    events = []
    await send(batch, beacon)
  }

  function push(event: SignalEvent): void {
    events.push(event)
    if (events.length >= FLUSH_AT) void flush()
  }

  return { push, flush, size: () => events.length }
}
