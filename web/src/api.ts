/**
 * The one module that knows the shape of the API.
 *
 * The Worker serves the built front from the same origin, so these are relative
 * paths and the session cookie rides along without any CORS or credentials
 * dance. In development Vite proxies /api to `wrangler dev`.
 */

export type Card = {
  cluster_id: number
  score: number
  similarity: number
  /** Cosine against what the reader hid. Zero for anyone who has hidden nothing. */
  penalty: number
  age_hours: number
  /** Profile terms that pushed this cluster up, strongest first. */
  because: string[]
  /** Hidden terms that pushed it down, strongest first. */
  against: string[]
  /** The cluster's own strongest terms, written by the ingestion job. */
  about: string[]
  title: string
  url: string
  source: string
  published_at: string
  /** How many articles the cluster holds, the anchor included. */
  size: number
  /** Portals other than the anchor's that ran the same story. */
  also_in: string[]
}

export type Feed = {
  user: { is_new: boolean; discovery_ratio: number }
  profile: { terms: number; empty: boolean; hidden_terms: number }
  feed: Card[]
  /**
   * Stories the reader's own hide pushed off the page.
   *
   * They are not part of the feed and must not be shown as if they were. The
   * penalty is larger than the spread of scores inside a page, so anything it
   * touches lands outside it, and without this list the reader would see one
   * cluster vanish and never learn the same gesture moved others.
   */
  held_back: Card[]
}

export type Signal = 'like' | 'hide'

export async function readFeed(signal?: AbortSignal): Promise<Feed> {
  const response = await fetch('/api/feed', { signal })
  if (!response.ok) {
    throw new Error(`feed respondeu ${response.status}`)
  }
  return response.json()
}

export async function record(cluster: number, type: Signal): Promise<void> {
  const response = await fetch('/api/interactions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ cluster_id: cluster, type }),
  })
  if (!response.ok) {
    throw new Error(`interacao respondeu ${response.status}`)
  }
}

/**
 * Age as a reader says it out loud, not as the API stores it.
 *
 * The API hands back hours as a float because that is what the decay curve
 * consumes; nobody reads "3.4 h".
 */
export function sayAge(hours: number): string {
  if (hours < 1) {
    const minutes = Math.max(1, Math.round(hours * 60))
    return `há ${minutes} min`
  }
  if (hours < 24) {
    return `há ${Math.round(hours)} h`
  }
  const days = Math.round(hours / 24)
  return days === 1 ? 'ontem' : `há ${days} dias`
}
