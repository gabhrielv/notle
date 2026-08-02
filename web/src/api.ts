/**
 * The one module that knows the shape of the API.
 *
 * The Worker serves the built front from the same origin, so these are relative
 * paths and the session cookie rides along without any CORS or credentials
 * dance. In development Vite proxies /api to `wrangler dev`.
 */

export type Card = {
  cluster_id: number
  title: string
  url: string
  source: string
  published_at: string
  /** How many articles the cluster holds, the anchor included. */
  size: number
  /** Portals other than the anchor's that ran the same story. */
  also_in: string[]
  /** The cluster's own strongest terms, written by the ingestion job. */
  about: string[]
  /** Profile terms that pushed this cluster up, strongest first. */
  because: string[]
  /** Hidden terms that pushed it down, strongest first. */
  against: string[]
  /**
   * Ranking output, and absent on the lists that do not rank. The chronological
   * page and the search results are ordered by the clock and by how well the
   * text matches, so a score there would be a number with nothing behind it.
   */
  score?: number
  similarity?: number
  penalty?: number
}

/** Every list answers in this shape, which is what lets one scroll drive them all. */
export type Page = {
  feed: Card[]
  /** Where to ask from next, or null when the list has run out. */
  next_offset: number | null
}

export type Feed = Page & {
  user: { is_new: boolean; discovery_ratio: number }
  profile: { terms: number; empty: boolean; hidden_terms: number }
}

export type Latest = Page & {
  hidden_shown: boolean
  hidden_count: number
}

export type Search = Page & { query: string }

export type Signal = 'like' | 'hide'

async function read<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal })
  if (!response.ok) {
    throw new Error(`${path} respondeu ${response.status}`)
  }
  return response.json()
}

export function readFeed(offset: number, signal?: AbortSignal): Promise<Feed> {
  return read(`/api/feed?offset=${offset}`, signal)
}

export function readLatest(
  offset: number,
  showHidden: boolean,
  signal?: AbortSignal,
): Promise<Latest> {
  return read(`/api/latest?offset=${offset}&hidden=${showHidden ? 1 : 0}`, signal)
}

export function readSearch(
  query: string,
  offset: number,
  signal?: AbortSignal,
): Promise<Search> {
  return read(`/api/search?q=${encodeURIComponent(query)}&offset=${offset}`, signal)
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
 * Age as a reader says it out loud.
 *
 * Computed from the timestamp rather than read off the card, because only the
 * ranked feed carries an age: the chronological and search lists never asked
 * the formula anything.
 */
export function sayAge(publishedAt: string): string {
  const hours = (Date.now() - Date.parse(publishedAt)) / 3_600_000

  if (!Number.isFinite(hours) || hours < 0) return 'agora'
  if (hours < 1) {
    const minutes = Math.max(1, Math.round(hours * 60))
    return `há ${minutes} min`
  }
  if (hours < 24) return `há ${Math.round(hours)} h`

  const days = Math.round(hours / 24)
  if (days === 1) return 'ontem'
  if (days < 30) return `há ${days} dias`

  const months = Math.round(days / 30)
  return months === 1 ? 'há um mês' : `há ${months} meses`
}
