import { ApiError } from './api'

/** Сбой, после которого запрос стоит повторять подольше: сервер перезапускается (выкатка) или сеть моргнула */
export function isTransient(error: unknown): boolean {
  if (error instanceof ApiError) return [502, 503, 504].includes(error.status)
  return error instanceof TypeError // fetch не достучался до сервера
}

/** Попыток при перезапуске сервера: с нарастающей паузой хватает примерно на минуту */
export const TRANSIENT_RETRIES = 10

export function shouldRetry(count: number, error: unknown): boolean {
  if (isTransient(error)) return count < TRANSIENT_RETRIES
  // 4xx — не сбой сервера, остальные 5xx повторяем недолго
  return !(error instanceof ApiError && error.status < 500) && count < 2
}

/** 1 с, 2 с, 4 с и дальше по 5 с */
export const retryDelay = (attempt: number): number => Math.min(1000 * 2 ** attempt, 5000)
