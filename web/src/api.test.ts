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
