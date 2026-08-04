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
