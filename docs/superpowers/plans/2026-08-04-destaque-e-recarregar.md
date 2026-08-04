# Destaque em carmim e recarregar por gesto: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Devolver o destaque carmim da primeira versão e acrescentar recarregar
por gesto de puxar para baixo nas listas.

**Architecture:** A cor é troca de valor em três variáveis CSS, em três blocos de
tema, mais a desinversão da marca. O gesto vive no componente de lista, apoiado
em dois módulos novos e puros: um que converte deslocamento do dedo em
deslocamento da lista, e outro que guarda a fila de sinais de forma que dê para
despachá-la e esperar. `useList` ganha `refresh`, e é ele que o gesto chama
depois que a fila chegou ao servidor.

**Tech Stack:** React 19, TypeScript, Vite 8, vitest (novo), CSS puro com
variáveis, pnpm.

## Global Constraints

- Código e comentários em inglês. Documentação de projeto em português.
- Sem em dashes em qualquer texto gerado.
- Nada de menção a assistente em mensagem de commit, comentário ou documentação.
- Sem dependência nova de runtime. O app promete funcionar offline e tem duas.
  `vitest` entra como dependência de desenvolvimento, que não vai para o bundle.
- Fontes, fundo, superfícies e layout não mudam. O pedido é de destaque.
- `pnpm --dir web lint` e `tsc -b` têm que continuar limpos: o deploy falha no
  passo de lint, e uma falha ali impede a migration de ser aplicada.

## Correção ao spec

O spec chama o componente de lista de `List`. O nome real é **`Stream`**, em
`web/src/App.tsx:127`. Onde o spec diz `List`, leia `Stream`.

---

### Task 1: Runner de teste no front

O projeto não tem nenhum. Sem isso as quatro tarefas seguintes não têm onde
rodar, e o spec promete testes.

**Files:**
- Modify: `web/package.json`
- Modify: `web/vite.config.ts`
- Modify: `.github/workflows/deploy.yml:52-56`
- Create: `web/src/pull.test.ts` (provisório, só para provar que o runner roda)

**Interfaces:**
- Consumes: nada.
- Produces: o comando `pnpm --dir web test`, usado por todas as tarefas
  seguintes.

- [ ] **Step 1: Instalar o vitest**

```bash
cd web && pnpm add -D vitest
```

- [ ] **Step 2: Declarar o script**

Em `web/package.json`, dentro de `scripts`, ao lado de `lint`:

```json
    "test": "vitest run",
```

- [ ] **Step 3: Configurar o ambiente**

Em `web/vite.config.ts`, acrescentar a chave `test` ao objeto de
`defineConfig`, depois de `server`:

```ts
  // Os testes daqui são de funções puras: aritmética de gesto e uma fila de
  // eventos. Nenhum toca DOM, então o ambiente de node serve e evita arrastar
  // jsdom para dentro de um projeto que tem duas dependências de runtime.
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
```

- [ ] **Step 4: Escrever um teste que prove o runner**

Criar `web/src/pull.test.ts`:

```ts
import { expect, test } from 'vitest'

test('o runner esta de pe', () => {
  expect(1 + 1).toBe(2)
})
```

- [ ] **Step 5: Rodar**

Run: `pnpm --dir web test`
Expected: 1 passed

- [ ] **Step 6: Fazer o CI rodar isso**

Em `.github/workflows/deploy.yml`, no passo `Lint`, acrescentar a linha do teste
depois de `pnpm --dir web lint`:

```yaml
      - name: Lint
        run: |
          uv run --group ingest --group dev ruff check src ingest scripts sim tests
          pnpm --dir web lint
          pnpm --dir web test
```

- [ ] **Step 7: Commit**

```bash
git add web/package.json web/pnpm-lock.yaml web/vite.config.ts web/src/pull.test.ts .github/workflows/deploy.yml
git commit -m "Give the front somewhere to put a test"
```

---

### Task 2: O destaque volta ao carmim

**Files:**
- Modify: `web/src/index.css:32-38` (tema claro)
- Modify: `web/src/index.css:60-66` (escuro por preferência do sistema)
- Modify: `web/src/index.css:77-83` (escuro por escolha explícita)
- Modify: `web/src/index.css:203-218` (`.wordmark`)

**Interfaces:**
- Consumes: nada.
- Produces: nada que outra tarefa use.

- [ ] **Step 1: Trocar as três variáveis no tema claro**

Em `web/src/index.css`, dentro de `:root`:

```css
  --accent: #c4005c;
  --accent-soft: #ffdfee;
```

e, mais abaixo no mesmo bloco:

```css
  --glow: rgba(196, 0, 92, 0.1);
```

- [ ] **Step 2: Trocar as mesmas três no bloco de `prefers-color-scheme: dark`**

Dentro de `:root:not([data-theme='light'])`:

```css
    --accent: #ff4d93;
    --accent-soft: #3d262f;
```

e:

```css
    --glow: rgba(255, 77, 147, 0.12);
```

- [ ] **Step 3: Trocar as mesmas três no bloco `:root[data-theme='dark']`**

```css
  --accent: #ff4d93;
  --accent-soft: #3d262f;
```

e:

```css
  --glow: rgba(255, 77, 147, 0.12);
```

- [ ] **Step 4: Desinverter a marca**

Hoje o nome inteiro usa o destaque e o ponto usa cinza, que é o contrário da
primeira versão. Em `.wordmark`, trocar a linha `color`:

```css
  color: var(--ink);
```

E em `.wordmark span`:

```css
.wordmark span {
  color: var(--accent);
}
```

- [ ] **Step 5: Verificar que não sobrou azul**

Run: `grep -nE '3a4bd0|b9c3ff|dfe3ff|262a3d|58, 75, 208|185, 195, 255' web/src/index.css`
Expected: nenhuma linha. Qualquer resultado é resíduo da paleta antiga.

- [ ] **Step 6: Verificar que o build continua limpo**

Run: `cd web && pnpm lint && ./node_modules/.bin/tsc -b`
Expected: sem saída de erro.

- [ ] **Step 7: Conferir na tela**

Run: `cd web && pnpm dev`
Abrir, e confirmar três coisas: `Notle` em quase preto com o ponto vermelho, o
círculo de contagem de portais em carmim quando a matéria saiu em mais de um
portal, e o mesmo no tema escuro pelo alternador.

- [ ] **Step 8: Commit**

```bash
git add web/src/index.css
git commit -m "Take the accent back to the crimson it started as"
```

---

### Task 3: `sendSignals` devolve algo que dá para esperar

**Files:**
- Modify: `web/src/api.ts:102-127`
- Create: `web/src/api.test.ts`

**Interfaces:**
- Consumes: `pnpm --dir web test` da Task 1.
- Produces: `sendSignals(sessionId: string, events: SignalEvent[], beacon?: boolean): Promise<void> | void`.
  Devolve promessa no caminho normal e `undefined` no caminho de beacon.

- [ ] **Step 1: Escrever os testes que falham**

Criar `web/src/api.test.ts`:

```ts
import { afterEach, expect, test, vi } from 'vitest'
import { sendSignals } from './api'

const EVENTS = [{ type: 'impression' as const, cluster_id: 1 }]

afterEach(() => {
  vi.unstubAllGlobals()
})

test('o caminho normal devolve uma promessa que da para esperar', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }))

  const sent = sendSignals('s1', EVENTS)

  expect(sent).toBeInstanceOf(Promise)
  await sent
  expect(fetch).toHaveBeenCalledOnce()
})

test('uma requisicao que falha nao rejeita, porque sinal implicito ajusta e nao decide', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('rede')))

  await expect(sendSignals('s1', EVENTS)).resolves.toBeUndefined()
})

test('o caminho de beacon nao devolve nada, porque sendBeacon nao da resposta', () => {
  const beacon = vi.fn().mockReturnValue(true)
  vi.stubGlobal('navigator', { sendBeacon: beacon })
  vi.stubGlobal('Blob', class {})

  expect(sendSignals('s1', EVENTS, true)).toBeUndefined()
  expect(beacon).toHaveBeenCalledOnce()
})
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `pnpm --dir web test`
Expected: FAIL. `sendSignals` devolve `undefined` no caminho normal, então
`expect(sent).toBeInstanceOf(Promise)` quebra.

- [ ] **Step 3: Devolver a promessa**

Em `web/src/api.ts`, trocar a assinatura e o corpo do caminho normal. O tipo de
retorno passa a ser `Promise<void> | void`, e o `void fetch(...)` vira `return`:

```ts
export function sendSignals(
  sessionId: string,
  events: SignalEvent[],
  beacon = false,
): Promise<void> | void {
  const body = JSON.stringify({ session_id: sessionId, events })

  // sendBeacon survives the page going away, which fetch does not reliably do.
  // It is only used on the way out, because it gives back no response and no
  // errors, so the ordinary path keeps something that can fail visibly.
  if (beacon && navigator.sendBeacon) {
    navigator.sendBeacon('/api/signals', new Blob([body], { type: 'application/json' }))
    return
  }

  // Handed back rather than fired and forgotten, because the pull gesture has
  // to know the queue landed before it asks for a fresh page. Between two
  // ingestions the ranking does not move, so what makes the stories change is
  // the repetition penalty, and that penalty is only applied to impressions the
  // server has actually received.
  return fetch('/api/signals', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body,
    keepalive: true,
  }).then(
    () => undefined,
    () => {
      // Losing a batch of implicit signal is not worth telling the reader about.
      // It adjusts; it does not decide. Swallowed here rather than rethrown, so
      // a refresh still happens when the network dropped the batch.
    },
  )
}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `pnpm --dir web test`
Expected: 4 passed (os 3 novos mais o da Task 1).

- [ ] **Step 5: Commit**

```bash
git add web/src/api.ts web/src/api.test.ts
git commit -m "Hand back the signal request instead of firing and forgetting"
```

---

### Task 4: A fila de sinais vira um módulo que dá para despachar

`useSignals` guarda a fila num `useRef` dentro do hook, então não há como testá-la
sem montar React. Extraída, ela é uma função pura de fábrica e o teste fica
direto.

**Files:**
- Create: `web/src/signalQueue.ts`
- Create: `web/src/signalQueue.test.ts`
- Modify: `web/src/useSignals.ts:10` (a constante `FLUSH_AT` sai daqui)
- Modify: `web/src/useSignals.ts:35-53` (fila e `flush` passam a vir do módulo)
- Modify: `web/src/useSignals.ts:124` (o retorno ganha `flush`)

**Interfaces:**
- Consumes: `SignalEvent` de `./api`.
- Produces:
  - `makeQueue(send: Send): { push(event: SignalEvent): void; flush(beacon?: boolean): Promise<void>; size(): number }`
  - `type Send = (events: SignalEvent[], beacon: boolean) => Promise<void> | void`
  - `useSignals(active: boolean)` passa a devolver `{ seen, clicked, flush }`,
    onde `flush: (beacon?: boolean) => Promise<void>`.

- [ ] **Step 1: Escrever os testes que falham**

Criar `web/src/signalQueue.test.ts`:

```ts
import { expect, test, vi } from 'vitest'
import { FLUSH_AT, makeQueue } from './signalQueue'

const event = (id: number) => ({ type: 'impression' as const, cluster_id: id })

test('uma fila vazia nao vira requisicao', async () => {
  const send = vi.fn()
  await makeQueue(send).flush()

  expect(send).not.toHaveBeenCalled()
})

test('despachar entrega o que foi enfileirado', async () => {
  const send = vi.fn()
  const queue = makeQueue(send)

  queue.push(event(1))
  queue.push(event(2))
  await queue.flush()

  expect(send).toHaveBeenCalledWith([event(1), event(2)], false)
})

test('a fila esvazia, entao despachar duas vezes nao manda o mesmo evento duas vezes', async () => {
  const send = vi.fn()
  const queue = makeQueue(send)

  queue.push(event(1))
  await queue.flush()
  await queue.flush()

  expect(send).toHaveBeenCalledOnce()
  expect(queue.size()).toBe(0)
})

test('a fila se despacha sozinha antes de crescer com uma rolagem longa', () => {
  const send = vi.fn()
  const queue = makeQueue(send)

  for (let i = 0; i < FLUSH_AT; i++) queue.push(event(i))

  expect(send).toHaveBeenCalledOnce()
  expect(queue.size()).toBe(0)
})

test('o pedido de beacon atravessa, porque a saida da pagina usa outro transporte', async () => {
  const send = vi.fn()
  const queue = makeQueue(send)

  queue.push(event(1))
  await queue.flush(true)

  expect(send).toHaveBeenCalledWith([event(1)], true)
})
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `pnpm --dir web test`
Expected: FAIL, `Cannot find module './signalQueue'`.

- [ ] **Step 3: Escrever o módulo**

Criar `web/src/signalQueue.ts`:

```ts
import type { SignalEvent } from './api'

/** Past this the queue goes early, rather than growing with a long scroll. */
export const FLUSH_AT = 20

/** How a batch actually leaves. Injected so the queue can be tested alone. */
export type Send = (events: SignalEvent[], beacon: boolean) => Promise<void> | void

/**
 * Holds measured events until something despatches them.
 *
 * A plain factory rather than state inside the hook, because the pull gesture
 * needs to await a despatch and a queue living in a `useRef` cannot be reached
 * or tested from outside React.
 *
 * The batch is taken out of the queue before it is sent, not after. Sending
 * first and clearing on success would send an event twice whenever a despatch
 * overlapped the next one, and these events are counted rather than merged.
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
```

- [ ] **Step 4: Rodar e ver passar**

Run: `pnpm --dir web test`
Expected: 9 passed.

- [ ] **Step 5: Usar o módulo dentro do hook**

Em `web/src/useSignals.ts`:

Remover a constante local `FLUSH_AT` e o comentário dela (linhas 9 e 10), e
acrescentar ao bloco de imports:

```ts
import { makeQueue } from './signalQueue'
```

Trocar a declaração da fila e o `flush` (o `queue` em `useRef` e o `flush` em
`useCallback`) por:

```ts
  const queue = useRef(
    makeQueue((events, beacon) => sendSignals(session.current, events, beacon)),
  )

  const flush = useCallback((beacon = false) => queue.current.flush(beacon), [])
```

E trocar o corpo de `push` para usar a fila do módulo:

```ts
  const push = useCallback(
    (event: SignalEvent) => {
      if (!active) return
      queue.current.push(event)
    },
    [active],
  )
```

- [ ] **Step 6: Expor `flush` no retorno**

Última linha da função `useSignals`:

```ts
  return { seen, clicked, flush }
```

- [ ] **Step 7: Verificar que nada quebrou**

Run: `pnpm --dir web test && cd web && pnpm lint && ./node_modules/.bin/tsc -b`
Expected: 9 passed, sem erro de lint nem de tipo.

- [ ] **Step 8: Commit**

```bash
git add web/src/signalQueue.ts web/src/signalQueue.test.ts web/src/useSignals.ts
git commit -m "Lift the signal queue out of the hook so it can be despatched"
```

---

### Task 5: A aritmética do gesto

**Files:**
- Modify: `web/src/pull.test.ts` (substitui o teste provisório da Task 1)
- Create: `web/src/pull.ts`

**Interfaces:**
- Consumes: `pnpm --dir web test` da Task 1.
- Produces:
  - `pullOffset(deltaY: number): number`
  - `shouldRefresh(offset: number): boolean`
  - `PULL_MAX: number` (96), `PULL_THRESHOLD: number` (64)

- [ ] **Step 1: Escrever os testes que falham**

Substituir todo o conteúdo de `web/src/pull.test.ts`:

```ts
import { expect, test } from 'vitest'
import { PULL_MAX, PULL_THRESHOLD, pullOffset, shouldRefresh } from './pull'

test('o dedo indo para cima nao puxa nada, porque isso e rolagem comum', () => {
  expect(pullOffset(-80)).toBe(0)
  expect(pullOffset(0)).toBe(0)
})

test('a lista acompanha amortecida, para o gesto ter resistencia', () => {
  expect(pullOffset(100)).toBe(50)
})

test('a lista para de acompanhar no teto, para nao sair da tela', () => {
  expect(pullOffset(1000)).toBe(PULL_MAX)
})

test('o teto fica acima do limiar, senao o gesto nunca poderia ser disparado', () => {
  expect(PULL_MAX).toBeGreaterThan(PULL_THRESHOLD)
})

test('soltar antes do limiar nao recarrega', () => {
  expect(shouldRefresh(PULL_THRESHOLD - 1)).toBe(false)
})

test('soltar no limiar recarrega', () => {
  expect(shouldRefresh(PULL_THRESHOLD)).toBe(true)
})
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `pnpm --dir web test`
Expected: FAIL, `Cannot find module './pull'`.

- [ ] **Step 3: Escrever o módulo**

Criar `web/src/pull.ts`:

```ts
/**
 * Turns finger travel into list travel.
 *
 * Damped rather than followed one to one: a list that tracks the finger exactly
 * reads as a bug in the scroll, while one that lags behind reads as something
 * being pulled against a spring. The numbers are proportions rather than
 * measurements, and the place to settle them is a real device.
 */

/** How much of the finger's travel the list actually takes. */
export const PULL_DAMPING = 0.5

/** Where the list stops following, well past the point the gesture is made. */
export const PULL_MAX = 96

/** Past this, releasing refreshes. Half of it in finger travel is 128px. */
export const PULL_THRESHOLD = 64

export function pullOffset(deltaY: number): number {
  if (deltaY <= 0) return 0
  return Math.min(deltaY * PULL_DAMPING, PULL_MAX)
}

export function shouldRefresh(offset: number): boolean {
  return offset >= PULL_THRESHOLD
}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `pnpm --dir web test`
Expected: 14 passed.

- [ ] **Step 5: Commit**

```bash
git add web/src/pull.ts web/src/pull.test.ts
git commit -m "Work out how far the list follows a finger"
```

---

### Task 6: O gesto na lista

**Files:**
- Modify: `web/src/useList.ts:72` (o retorno ganha `refresh`)
- Modify: `web/src/useList.ts:59-62` (ao lado de `more`)
- Modify: `web/src/App.tsx:127-148` (o componente `Stream`)
- Modify: `web/src/App.tsx:149-184` (a marcação de `Stream`)
- Modify: `web/src/index.css` (fim do arquivo: o indicador)

**Interfaces:**
- Consumes: `pullOffset`, `shouldRefresh`, `PULL_MAX` de `./pull`; `flush` de
  `useSignals`; `refresh` de `useList`.
- Produces: nada que outra tarefa use.

- [ ] **Step 1: Dar `refresh` ao `useList`**

Em `web/src/useList.ts`, logo depois de `more`:

```ts
  /**
   * Loads the first page again, replacing what is there.
   *
   * Separate from `retry`, which resumes from where a failure left off. This one
   * always starts over, because the reader asked for a fresh list rather than
   * for the last request to be attempted again.
   */
  const refresh = useCallback(() => {
    fetchPage(0, currentKey.current)
  }, [fetchPage])
```

E acrescentar ao retorno:

```ts
  return { items, busy, failed, offline, exhausted: next === null, more, retry, refresh, drop }
```

- [ ] **Step 2: Verificar que nada quebrou**

Run: `cd web && ./node_modules/.bin/tsc -b`
Expected: sem erro.

- [ ] **Step 3: Ligar o gesto no `Stream`**

Em `web/src/App.tsx`, trocar a primeira linha de import por:

```ts
import { useCallback, useEffect, useRef, useState } from 'react'
import type { TouchEvent } from 'react'
```

`useRef` não estava importado, e o tipo do evento precisa vir por `import type`
porque o projeto usa `verbatimModuleSyntax`.

Acrescentar, junto dos outros imports locais:

```ts
import { pullOffset, shouldRefresh } from './pull'
```

Importar só o que se usa: `noUnusedLocals` está ligado, então um `PULL_MAX`
importado e não usado derruba o build.

Dentro de `Stream`, trocar a linha que desestrutura `useSignals`:

```ts
  const { seen, clicked, flush } = useSignals(canAct)
```

E acrescentar o estado e os manipuladores logo depois de `const sentinel = ...`:

```ts
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
    // make the gesture look broken.
    void flush()
      .then(() => list.refresh())
      .finally(() => setRefreshing(false))
  }, [pull, flush, list.refresh])
```

`list` já existe no escopo: é o `const list = useList(load, listKey)` da primeira
linha de `Stream`. A dependência é `list.refresh` e não `list`, porque `useList`
devolve um objeto novo a cada render e depender dele recriaria o manipulador sem
motivo.
```

- [ ] **Step 4: Pendurar os manipuladores e o indicador na marcação**

`Stream` devolve um fragmento: `<>` logo depois de `return (`, e `</>` na última
linha antes do `)` que fecha. Os dois viram uma `div`.

Trocar a linha `    <>` por:

```tsx
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
```

E trocar a linha `    </>` por:

```tsx
    </div>
```

O `.shell` que contém isso é um bloco comum com largura máxima, então uma
camada a mais não muda o layout.

- [ ] **Step 5: Estilizar o indicador**

No fim de `web/src/index.css`:

```css
/* The whole list slides down from here, so the label is parked just above the
   top edge and is carried into view by the same movement. Positioned rather
   than laid out, because a label that took up space would push the first card
   down by its own height while nobody was pulling anything. */
.pullable {
  position: relative;
  transition: transform 0.2s ease-out;
}

.pull {
  position: absolute;
  top: -1.75rem;
  left: 0;
  right: 0;
  margin: 0;
  color: var(--ink-2);
  font-family: var(--mono);
  font-size: 0.688rem;
  letter-spacing: 0.09em;
  text-align: center;
}

/* Snapping back is the part that reads as motion. Someone who asked for less of
   it gets the position without the travel. */
@media (prefers-reduced-motion: reduce) {
  .pullable {
    transition: none;
  }
}
```

- [ ] **Step 6: Verificar tipos e lint**

Run: `cd web && pnpm lint && ./node_modules/.bin/tsc -b && cd .. && pnpm --dir web test`
Expected: sem erro, 14 passed.

- [ ] **Step 7: Conferir no aparelho**

Run: `cd web && pnpm dev --host`

Abrir pelo celular no endereço de rede que o Vite imprime, e confirmar:
no topo da lista, puxar para baixo move a lista com resistência e o rótulo muda
para "solte para atualizar" passando do limiar; soltar mostra "atualizando" e
depois traz uma lista com matérias diferentes das que estavam na tela; puxar no
meio da lista não faz nada; arrastar para cima no fim continua carregando mais.

- [ ] **Step 8: Commit**

```bash
git add web/src/useList.ts web/src/App.tsx web/src/index.css
git commit -m "Let the reader ask the feed for another turn"
```

---

## Verificação final

- [ ] `pnpm --dir web test` passa com 14 testes.
- [ ] `pnpm --dir web lint` e `tsc -b` limpos.
- [ ] `grep -nE '3a4bd0|b9c3ff|dfe3ff|262a3d' web/src/index.css` não devolve nada.
- [ ] `uv run --group ingest --group dev ruff check src ingest scripts sim tests` continua limpo, porque o passo de lint do deploy roda os dois e uma falha ali impede a migration.
- [ ] Conferido no celular nos dois temas.
