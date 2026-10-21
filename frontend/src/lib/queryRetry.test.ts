import { describe, expect, it } from 'vitest'
import { ApiError } from './api'
import { isTransient, retryDelay, shouldRetry, TRANSIENT_RETRIES } from './queryRetry'

describe('isTransient', () => {
  it.each([502, 503, 504])('ответ %i — сервер перезапускается', (status) => {
    expect(isTransient(new ApiError(status, 'x'))).toBe(true)
  })

  it.each([400, 401, 404, 409, 500])('ответ %i — не перезапуск сервера', (status) => {
    expect(isTransient(new ApiError(status, 'x'))).toBe(false)
  })

  it('fetch не достучался до сервера (TypeError) — тоже перезапуск или сеть', () => {
    expect(isTransient(new TypeError('Failed to fetch'))).toBe(true)
  })

  it('прочие ошибки не считаются сбоем сервера', () => {
    expect(isTransient(new Error('что-то'))).toBe(false)
    expect(isTransient(null)).toBe(false)
  })
})

describe('shouldRetry', () => {
  it('при перезапуске сервера повторяет до TRANSIENT_RETRIES раз', () => {
    const error = new ApiError(503, 'x')
    expect(shouldRetry(0, error)).toBe(true)
    expect(shouldRetry(TRANSIENT_RETRIES - 1, error)).toBe(true)
    expect(shouldRetry(TRANSIENT_RETRIES, error)).toBe(false)
  })

  it('сетевой сбой повторяет так же долго', () => {
    expect(shouldRetry(5, new TypeError('Failed to fetch'))).toBe(true)
  })

  it('4xx не повторяет совсем', () => {
    expect(shouldRetry(0, new ApiError(404, 'x'))).toBe(false)
    expect(shouldRetry(0, new ApiError(409, 'x'))).toBe(false)
  })

  it('обычная 5xx и прочие ошибки — не больше двух повторов', () => {
    expect(shouldRetry(1, new ApiError(500, 'x'))).toBe(true)
    expect(shouldRetry(2, new ApiError(500, 'x'))).toBe(false)
    expect(shouldRetry(1, new Error('x'))).toBe(true)
    expect(shouldRetry(2, new Error('x'))).toBe(false)
  })
})

describe('retryDelay', () => {
  it('растёт 1, 2, 4 секунды и не дольше 5 секунд', () => {
    expect([0, 1, 2, 3, 9].map(retryDelay)).toEqual([1000, 2000, 4000, 5000, 5000])
  })

  it('все повторы укладываются примерно в минуту', () => {
    const total = Array.from({ length: TRANSIENT_RETRIES }, (_, i) => retryDelay(i)).reduce((a, b) => a + b, 0)
    expect(total).toBeGreaterThan(30_000)
    expect(total).toBeLessThan(90_000)
  })
})
