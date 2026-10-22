import { useSyncExternalStore } from 'react'
import { safeStorage } from './storage'

const KEY = 'hmsrent:problems-seen'
const listeners = new Set<() => void>()

const read = () => Number(safeStorage.get(KEY)) || 0

function subscribe(listener: () => void) {
  listeners.add(listener)
  window.addEventListener('storage', listener) // другая вкладка того же браузера
  return () => {
    listeners.delete(listener)
    window.removeEventListener('storage', listener)
  }
}

/** Номер последней проблемы, которую исполнитель уже видел (больше — новые); хранится в браузере */
export const useSeenProblemId = () => useSyncExternalStore(subscribe, read)

/** Запоминает, что проблемы до `id` включительно просмотрены; меньшее число прежнее не затирает */
export function markProblemsSeen(id: number) {
  if (id <= read()) return
  safeStorage.set(KEY, String(id))
  listeners.forEach((listener) => listener())
}
