import { useCallback, useEffect, useRef, useState } from 'react'
import type { Card, Page } from './api'

export type Loader = (offset: number, signal: AbortSignal) => Promise<Page>

/**
 * One list, loaded a page at a time as the reader scrolls.
 *
 * `key` identifies what is being listed: the route, plus whatever the reader
 * can change about it, such as the search text or whether hidden stories are
 * shown. When it changes the list starts over from the top, and every response
 * still in flight for the old key is dropped rather than appended, which is what
 * stops results for a half typed search arriving under a finished one.
 */
export function useList(load: Loader, key: string) {
  const [items, setItems] = useState<Card[]>([])
  const [next, setNext] = useState<number | null>(0)
  const [busy, setBusy] = useState(true)
  const [failed, setFailed] = useState(false)

  const currentKey = useRef(key)
  const loader = useRef(load)
  loader.current = load

  const fetchPage = useCallback((offset: number, forKey: string) => {
    const controller = new AbortController()

    setBusy(true)
    setFailed(false)

    loader
      .current(offset, controller.signal)
      .then((page) => {
        if (currentKey.current !== forKey) return
        setItems((previous) => (offset === 0 ? page.feed : [...previous, ...page.feed]))
        setNext(page.next_offset)
        setBusy(false)
      })
      .catch(() => {
        if (currentKey.current !== forKey || controller.signal.aborted) return
        setFailed(true)
        setBusy(false)
      })

    return controller
  }, [])

  useEffect(() => {
    currentKey.current = key
    setItems([])
    setNext(0)

    const controller = fetchPage(0, key)
    return () => controller.abort()
  }, [key, fetchPage])

  const more = useCallback(() => {
    if (busy || next === null) return
    fetchPage(next, currentKey.current)
  }, [busy, next, fetchPage])

  const retry = useCallback(() => {
    fetchPage(items.length ? (next ?? 0) : 0, currentKey.current)
  }, [fetchPage, items.length, next])

  const drop = useCallback((cluster: number) => {
    setItems((previous) => previous.filter((card) => card.cluster_id !== cluster))
  }, [])

  return { items, busy, failed, exhausted: next === null, more, retry, drop }
}

/**
 * Calls `onReach` when the element it returns scrolls into view.
 *
 * The margin fires it well before the sentinel is actually visible, so the next
 * page is already arriving by the time the reader gets to the bottom and the
 * scroll never stops to wait.
 */
export function useSentinel(onReach: () => void, active: boolean) {
  const ref = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const node = ref.current
    if (!active || !node) return

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) onReach()
      },
      { rootMargin: '800px' },
    )

    observer.observe(node)
    return () => observer.disconnect()
  }, [onReach, active])

  return ref
}
