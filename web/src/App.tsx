import { useCallback, useEffect, useRef, useState } from 'react'
import type { TouchEvent } from 'react'
import { Card } from './Card'
import { Onboarding } from './Onboarding'
import {
  answerOnboarding,
  readFeed,
  readLatest,
  readSearch,
  record,
  setDiscovery,
} from './api'
import type { Feed, Signal } from './api'
import { useTheme } from './theme'
import { pullOffset, shouldRefresh } from './pull'
import { useList, useSentinel } from './useList'
import { useSignals } from './useSignals'
import type { Loader } from './useList'

/**
 * Below this the skeleton is worse than nothing: it paints and clears inside
 * one frame or two, which reads as a flicker rather than as progress.
 */
const SKELETON_AFTER_MS = 200

/** Long enough for the card to finish leaving before it stops existing. */
const LEAVE_MS = 240

/** Long enough that a search runs on a word, not on every letter of one. */
const TYPING_SETTLES_MS = 350

type Route = 'feed' | 'latest' | 'search'

const PATHS: Record<Route, string> = {
  feed: '/',
  latest: '/ultimas',
  search: '/buscar',
}

const LABELS: Record<Route, string> = {
  feed: 'Para você',
  latest: 'Últimas',
  search: 'Buscar',
}

function routeOf(pathname: string): Route {
  if (pathname.startsWith(PATHS.latest)) return 'latest'
  if (pathname.startsWith(PATHS.search)) return 'search'
  return 'feed'
}

/**
 * Real URLs rather than tab state, so a page can be linked and the back button
 * means what it looks like it means. The Worker serves the built front for any
 * path it does not handle, which is what makes a deep link work on reload.
 */
function useRoute(): [Route, (to: Route) => void] {
  const [route, setRoute] = useState<Route>(() => routeOf(window.location.pathname))

  useEffect(() => {
    const onPop = () => setRoute(routeOf(window.location.pathname))
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  const go = useCallback((to: Route) => {
    window.history.pushState(null, '', PATHS[to])
    setRoute(to)
    window.scrollTo({ top: 0 })
  }, [])

  return [route, go]
}

/** Records a signal and takes the card out of whichever list it was in. */
function useActions(drop: (cluster: number) => void) {
  const [busy, setBusy] = useState<number | null>(null)
  const [leaving, setLeaving] = useState<number[]>([])
  const [problem, setProblem] = useState<string | null>(null)

  const act = useCallback(
    async (cluster: number, type: Signal) => {
      setBusy(cluster)
      setProblem(null)
      try {
        await record(cluster, type)
        setLeaving((current) => [...current, cluster])
        setTimeout(() => drop(cluster), LEAVE_MS)
      } catch {
        setProblem('Não deu para registrar. A matéria segue na lista.')
      } finally {
        setBusy(null)
      }
    },
    [drop],
  )

  return { act, busy, leaving, problem }
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

type StreamProps = {
  load: Loader
  listKey: string
  canAct: boolean
  emptyTitle: string
  emptyBody: string
  children?: React.ReactNode
}

/** One scrolling list. Every route is this, with a different loader. */
function Stream({ load, listKey, canAct, emptyTitle, emptyBody, children }: StreamProps) {
  const list = useList(load, listKey)
  const { act, busy, leaving, problem } = useActions(list.drop)
  // The same switch that hides the buttons stops the measuring. An anonymous
  // search promises nothing is recorded, and that promise is kept by there
  // being nothing to record rather than by a flag the server has to honour.
  const { seen, clicked, flush } = useSignals(canAct)
  const [slow, setSlow] = useState(false)

  const firstLoad = list.busy && list.items.length === 0

  useEffect(() => {
    if (!firstLoad) {
      setSlow(false)
      return
    }
    const timer = setTimeout(() => setSlow(true), SKELETON_AFTER_MS)
    return () => clearTimeout(timer)
  }, [firstLoad])

  const sentinel = useSentinel(list.more, !list.exhausted && !list.failed)

  // Where the finger went down, or nothing when the gesture is not armed. It
  // only arms at the very top: anywhere else a downward finger is ordinary
  // scrolling, and stealing that would break the page.
  const from = useRef<number | null>(null)
  const [pull, setPull] = useState(0)
  const [refreshing, setRefreshing] = useState(false)

  const onTouchStart = useCallback(
    (event: TouchEvent) => {
      if (refreshing || window.scrollY > 0) return
      from.current = event.touches[0].clientY
    },
    [refreshing],
  )

  const onTouchMove = useCallback((event: TouchEvent) => {
    if (from.current === null) return
    setPull(pullOffset(event.touches[0].clientY - from.current))
  }, [])

  // Not an async handler. React types a touch handler as returning nothing, and
  // an async one returns a promise nobody is holding, so the chain is written
  // out instead.
  const onTouchEnd = useCallback(() => {
    if (from.current === null) return
    from.current = null

    const reached = shouldRefresh(pull)
    setPull(0)
    if (!reached) return

    setRefreshing(true)
    // The despatch comes first and is waited on. Between two ingestions the
    // ranking does not move, so what makes the stories change is the repetition
    // penalty, and that only counts impressions the server has already been
    // told about. Reloading straight away would hand back the same list and
    // make the gesture look broken exactly when it is used hardest.
    void flush()
      .then(() => list.refresh())
      .finally(() => setRefreshing(false))
  }, [pull, flush, list.refresh])

  return (
    <div
      className="pullable"
      onTouchStart={onTouchStart}
      onTouchMove={onTouchMove}
      onTouchEnd={onTouchEnd}
      style={{ transform: `translateY(${pull}px)` }}
    >
      <p className="pull" aria-hidden={pull === 0 && !refreshing}>
        {refreshing
          ? 'atualizando'
          : shouldRefresh(pull)
            ? 'solte para atualizar'
            : 'puxe para atualizar'}
      </p>
      {children}
      {problem && <p className="hint">{problem}</p>}

      {list.offline && (
        <p className="hint">
          Você está sem conexão e ainda não havia nada guardado neste aparelho.
          Volte quando a rede voltar, ou abra o site uma vez com conexão para que
          o último feed fique disponível offline.
        </p>
      )}

      {firstLoad && slow && <Skeleton />}

      {list.items.length > 0 && (
        <ul className="feed">
          {list.items.map((card, i) => (
            <Card
              key={card.cluster_id}
              card={card}
              index={i}
              isLead={i === 0}
              leaving={leaving.includes(card.cluster_id)}
              busy={busy === card.cluster_id}
              canAct={canAct}
              onAct={act}
              onSeen={seen}
              onOpen={clicked}
            />
          ))}
        </ul>
      )}

      <div ref={sentinel} aria-hidden="true" />

      {list.busy && list.items.length > 0 && (
        <p className="more" role="status">
          carregando mais
        </p>
      )}

      {list.exhausted && list.items.length > 0 && (
        <p className="more">acabou por aqui</p>
      )}

      {list.failed && (
        <section className="notice">
          <h2 className="notice-title">Não carregou</h2>
          <p className="notice-body">
            A chamada para a API não voltou. Pode ser a rede ou o banco.
          </p>
          <button type="button" className="action" onClick={list.retry}>
            Tentar de novo
          </button>
        </section>
      )}

      {!list.busy && !list.failed && list.items.length === 0 && (
        <section className="notice">
          <h2 className="notice-title">{emptyTitle}</h2>
          <p className="notice-body">{emptyBody}</p>
        </section>
      )}
    </div>
  )
}

function FeedView() {
  const [profile, setProfile] = useState<Feed['profile'] | null>(null)
  const [isNew, setIsNew] = useState(false)
  const [cold, setCold] = useState<Feed['onboarding'] | null>(null)
  const [run, setRun] = useState<Feed['session'] | null>(null)
  const [ratio, setRatio] = useState<number | null>(null)
  // Bumped when the cold start is answered, so the list reloads against the
  // profile that answer just created rather than the empty one behind it.
  const [generation, setGeneration] = useState(0)

  const load = useCallback<Loader>(async (offset, signal) => {
    const page = await readFeed(offset, signal)
    setProfile(page.profile)
    setIsNew(page.user.is_new)
    setRun(page.session)
    setRatio((current) => (current === null ? page.user.discovery_ratio : current))
    if (offset === 0) setCold(page.onboarding)
    return page
  }, [])

  // Saved on release rather than on every pixel: the slider fires continuously
  // while dragged, and the reload it triggers is a whole ranked page.
  const slide = useCallback(async (next: number) => {
    setRatio(next)
    await setDiscovery(next)
    setGeneration((n) => n + 1)
  }, [])

  const finish = useCallback(async (picks: number[]) => {
    await answerOnboarding(picks)
    setCold(null)
    setGeneration((n) => n + 1)
  }, [])

  if (cold?.pending && cold.feed.length > 0) {
    return <Onboarding offer={cold.feed} picks={cold.picks} onDone={finish} />
  }

  return (
    <Stream
      load={load}
      listKey={`feed:${generation}`}
      canAct
      emptyTitle="Nada na janela agora"
      emptyBody="A ingestão lê os portais de hora em hora, e o feed olha as últimas 48 horas. Se você respondeu a tudo, volte depois da próxima passada."
    >
      <div className="panel">
        <p className="standfirst">
          {profile
            ? profile.empty && !profile.hidden_terms
              ? 'ordenado por recência, ainda sem gosto registrado'
              : `${profile.terms} termos de gosto, ${profile.hidden_terms} escondidos`
            : 'lendo a janela'}
        </p>
        {ratio !== null && (
          <label className="slider">
            <span>bolha</span>
            <input
              type="range"
              min={0}
              max={0.5}
              step={0.05}
              value={ratio}
              onChange={(event) => setRatio(Number(event.target.value))}
              onMouseUp={(event) => slide(Number(event.currentTarget.value))}
              onTouchEnd={(event) => slide(Number(event.currentTarget.value))}
              onKeyUp={(event) => slide(Number(event.currentTarget.value))}
              aria-label="Quanto do feed é reservado a descoberta"
            />
            <span>descoberta</span>
            <span className="slider-value">
              {ratio === 0
                ? 'nenhum slot reservado'
                : `${Math.round(ratio * 100)}% dos slots`}
            </span>
          </label>
        )}

        {run?.about && (
          <p className="run">
            <span className="run-label" aria-hidden="true" />
            agora · você está numa sequência sobre <b>{run.about}</b>
          </p>
        )}
      </div>
      {isNew && (
        <p className="hint">
          Interessa e ocultar ensinam o feed. A matéria sai da lista e o próximo
          carregamento já leva em conta o que você marcou.
        </p>
      )}
    </Stream>
  )
}

function LatestView() {
  const [showHidden, setShowHidden] = useState(false)
  const [hiddenCount, setHiddenCount] = useState(0)

  const load = useCallback<Loader>(
    async (offset, signal) => {
      const page = await readLatest(offset, showHidden, signal)
      if (!page.hidden_shown) setHiddenCount(page.hidden_count)
      return page
    },
    [showHidden],
  )

  return (
    <Stream
      load={load}
      listKey={`latest:${showHidden}`}
      canAct
      emptyTitle="O corpus está vazio"
      emptyBody="Nenhuma matéria foi ingerida ainda. A primeira passada roda de hora em hora."
    >
      <div className="panel">
        <p className="standfirst">tudo que chegou, da mais nova para a mais velha</p>
        {hiddenCount > 0 && (
          <label className="switch">
            <input
              type="checkbox"
              checked={showHidden}
              onChange={(event) => setShowHidden(event.target.checked)}
            />
            <span>mostrar as {hiddenCount} que você ocultou</span>
          </label>
        )}
      </div>
    </Stream>
  )
}

function SearchView() {
  const [typed, setTyped] = useState('')
  const [query, setQuery] = useState('')
  const [anonymous, setAnonymous] = useState(false)

  // The list restarts on every key of `query`, so settling it first is what
  // keeps a five letter word from being four abandoned searches.
  useEffect(() => {
    const timer = setTimeout(() => setQuery(typed.trim()), TYPING_SETTLES_MS)
    return () => clearTimeout(timer)
  }, [typed])

  const load = useCallback<Loader>(
    (offset, signal) => readSearch(query, offset, signal),
    [query],
  )

  return (
    <>
      <form className="searchbar" onSubmit={(event) => event.preventDefault()}>
        <input
          className="searchbox"
          type="search"
          value={typed}
          onChange={(event) => setTyped(event.target.value)}
          placeholder="Buscar no acervo"
          aria-label="Buscar no acervo"
          autoFocus
        />
        <label className="switch">
          <input
            type="checkbox"
            checked={anonymous}
            onChange={(event) => setAnonymous(event.target.checked)}
          />
          <span>busca anônima</span>
        </label>
      </form>

      {anonymous && (
        <p className="hint">
          Nada desta busca chega ao seu perfil. Interessa e ocultar são o único
          jeito de ensinar o algoritmo, então eles somem daqui enquanto o modo
          estiver ligado.
        </p>
      )}

      {query ? (
        <Stream
          load={load}
          listKey={`search:${query}`}
          canAct={!anonymous}
          emptyTitle="Nada encontrado"
          emptyBody={`Nenhuma matéria do acervo casa com "${query}". A busca exige todas as palavras, então tirar uma costuma trazer resultado.`}
        />
      ) : (
        <section className="notice">
          <h2 className="notice-title">Busque no acervo inteiro</h2>
          <p className="notice-body">
            Procura por manchete e resumo de tudo que já foi ingerido, sem passar
            pelo seu gosto. Acento não importa: "eleicao" acha "eleição".
          </p>
        </section>
      )}
    </>
  )
}

/** Drawn here rather than pulled from an icon font, which would not load offline. */
const ICONS: Record<Route, React.ReactNode> = {
  feed: (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <path d="M3 10a7 7 0 0 1 7 7M3 4a13 13 0 0 1 13 13" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <circle cx="4" cy="16" r="1.4" fill="currentColor" />
    </svg>
  ),
  latest: (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <circle cx="10" cy="10" r="7" stroke="currentColor" strokeWidth="1.6" />
      <path d="M10 6v4.3l2.8 1.7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  ),
  search: (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <circle cx="9" cy="9" r="5.5" stroke="currentColor" strokeWidth="1.6" />
      <path d="m13.2 13.2 3.3 3.3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  ),
}

function Tabs({ route, go }: { route: Route; go: (to: Route) => void }) {
  return (
    <>
      {(Object.keys(PATHS) as Route[]).map((name) => (
        <button
          key={name}
          type="button"
          className={`tab${route === name ? ' is-current' : ''}`}
          aria-current={route === name ? 'page' : undefined}
          onClick={() => go(name)}
        >
          {ICONS[name]}
          <span>{LABELS[name]}</span>
        </button>
      ))}
    </>
  )
}

function Theme() {
  const [theme, toggleTheme] = useTheme()
  const dark = theme === 'dark'

  return (
    <button
      type="button"
      className="theme"
      onClick={toggleTheme}
      aria-label={dark ? 'Usar tema claro' : 'Usar tema escuro'}
    >
      <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
        {dark ? (
          <>
            <circle cx="8" cy="8" r="3.2" stroke="currentColor" strokeWidth="1.4" />
            <path
              d="M8 1v1.6M8 13.4V15M1 8h1.6M13.4 8H15M3.1 3.1l1.1 1.1M11.8 11.8l1.1 1.1M12.9 3.1l-1.1 1.1M4.2 11.8l-1.1 1.1"
              stroke="currentColor"
              strokeWidth="1.4"
              strokeLinecap="round"
            />
          </>
        ) : (
          <path
            d="M13.5 9.6A6 6 0 0 1 6.4 2.5a6 6 0 1 0 7.1 7.1Z"
            stroke="currentColor"
            strokeWidth="1.4"
            strokeLinejoin="round"
          />
        )}
      </svg>
      {dark ? 'claro' : 'escuro'}
    </button>
  )
}

export default function App() {
  const [route, go] = useRoute()

  return (
    <>
      {/* The navigation leaves the reading column on desktop, which is what
          gives the headlines the full width of the centre back. */}
      <nav className="rail" aria-label="Seções">
        <div>
          <button className="wordmark" type="button" onClick={() => go('feed')}>
            Notle<span>.</span>
          </button>
          <p className="tagline">feed explicável</p>
        </div>
        <div className="rail-nav">
          <Tabs route={route} go={go} />
        </div>
        <div className="rail-foot">
          <Theme />
        </div>
      </nav>

      <header className="topbar">
        <button className="wordmark" type="button" onClick={() => go('feed')}>
          Notle<span>.</span>
        </button>
        <Theme />
      </header>

      <main className="shell">
        {route === 'feed' && <FeedView />}
        {route === 'latest' && <LatestView />}
        {route === 'search' && <SearchView />}
      </main>

      <nav className="bar" aria-label="Seções">
        <Tabs route={route} go={go} />
      </nav>
    </>
  )
}
