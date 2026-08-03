/**
 * Serve o que já tem e revalida atrás da tela.
 *
 * Escrito à mão em vez de gerado por plugin, e a razão é a mesma que manteve o
 * Worker sem framework: o projeto inteiro tem duas dependências de runtime, e um
 * gerador de service worker traria mais configuração do que o arquivo tem
 * linhas.
 *
 * Cache em tempo de execução, não pré-cache. Sem plugin de build não há como
 * saber os nomes com hash que o Vite gera, e tentar adivinhá-los seria uma lista
 * que quebra em silêncio no próximo deploy. A consequência aceita: a primeira
 * visita não funciona offline, porque não há o que servir ainda. A segunda sim,
 * que é justamente a visita em que offline importa.
 */

// Trocar isto invalida tudo. É o que faz um deploy novo não ser servido do
// cache antigo para sempre.
const VERSION = 'notle-v1'

const SHELL = `${VERSION}-shell`
const DATA = `${VERSION}-data`

// O que vale guardar de API. Só a primeira página do feed e das últimas: é o
// que uma volta ao site mostra de imediato. Busca não entra porque cada consulta
// é uma chave diferente e o cache viraria um log do que a pessoa procurou.
const CACHEABLE = ['/api/feed?offset=0', '/api/latest?offset=0']

self.addEventListener('install', (event) => {
  // Assume o controle sem esperar a aba fechar. Sem isso o service worker novo
  // fica parado até a próxima visita, e um deploy demoraria duas sessões para
  // valer.
  event.waitUntil(self.skipWaiting())
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const names = await caches.keys()
      await Promise.all(
        names.filter((name) => !name.startsWith(VERSION)).map((name) => caches.delete(name)),
      )
      await self.clients.claim()
    })(),
  )
})

/** Uma chave de cache que ignora o que não muda a resposta. */
function keyFor(url) {
  const clean = new URL(url)
  clean.searchParams.delete('session')
  return clean.pathname + clean.search
}

function isCacheableData(url) {
  const key = keyFor(url)
  return CACHEABLE.some((path) => key === path || key === path.split('?')[0])
}

/**
 * Devolve o que está guardado na hora e busca o novo por trás.
 *
 * É o maior ganho de percepção que o projeto tem: quem volta vê notícia de
 * verdade imediatamente, e a latência do banco acontece invisível atrás de uma
 * tela já preenchida.
 */
async function staleWhileRevalidate(request) {
  const cache = await caches.open(DATA)
  const key = keyFor(request.url)
  const cached = await cache.match(key)

  const fresh = fetch(request)
    .then((response) => {
      if (response.ok) cache.put(key, response.clone())
      return response
    })
    .catch(() => null)

  if (cached) {
    // A revalidação segue sozinha. Não é esperada nem tratada: se falhar, o
    // leitor já está lendo o que tinha.
    fresh.catch(() => {})
    return cached
  }

  const response = await fresh
  if (response) return response

  // Primeira visita sem rede. Não há o que servir e mentir seria pior.
  return new Response(JSON.stringify({ offline: true, feed: [], next_offset: null }), {
    status: 503,
    headers: { 'Content-Type': 'application/json' },
  })
}

/** Cache primeiro para o que tem nome versionado, rede primeiro para o resto. */
async function shell(request) {
  const cache = await caches.open(SHELL)
  const cached = await cache.match(request)
  if (cached) return cached

  try {
    const response = await fetch(request)
    if (response.ok) cache.put(request, response.clone())
    return response
  } catch (error) {
    void error
    // Navegação sem rede cai no index guardado, e o React resolve a rota do
    // lado do cliente. Sem isso, abrir /ultimas offline seria a tela de erro do
    // navegador em vez do último feed.
    if (request.mode === 'navigate') {
      const index = await cache.match('/index.html')
      if (index) return index
    }
    throw error
  }
}

self.addEventListener('fetch', (event) => {
  const { request } = event

  // Só GET. Um like ou um lote de sinais que voltasse do cache seria uma
  // escrita que o leitor acha que aconteceu e não aconteceu.
  if (request.method !== 'GET') return

  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return

  if (url.pathname.startsWith('/api/')) {
    if (isCacheableData(url)) event.respondWith(staleWhileRevalidate(request))
    return
  }

  event.respondWith(shell(request))
})
