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
