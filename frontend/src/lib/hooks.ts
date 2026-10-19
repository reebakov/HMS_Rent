import { useEffect, useRef } from 'react'

/**
 * Применяет строку поиска через delay мс после последнего ввода, чтобы не дёргать API на каждую букву.
 * Значение, равное уже применённому, не применяется: иначе таймер, сработавший после монтирования или после
 * возврата к тому же тексту, сбрасывал бы страницу и выделение, хотя поиск никто не менял.
 */
export function useDebouncedSearch(search: string, applied: string | undefined, apply: (q: string | undefined) => void, delay = 250) {
  // актуальные значения без перезапуска таймера на каждый рендер
  const latest = useRef({ applied, apply })
  latest.current = { applied, apply }

  useEffect(() => {
    const timer = setTimeout(() => {
      const q = search.trim() || undefined
      if (q !== latest.current.applied) latest.current.apply(q)
    }, delay)
    return () => clearTimeout(timer)
  }, [search, delay])
}

/** Можно ли отреагировать на одиночную клавишу: человек не печатает в поле, нет сочетания с Ctrl/Alt/⌘ и не открыто окно */
export function canUseHotkey(e: KeyboardEvent) {
  if (e.ctrlKey || e.metaKey || e.altKey) return false
  const target = e.target as HTMLElement | null
  if (target && (target.isContentEditable || ['INPUT', 'SELECT', 'TEXTAREA'].includes(target.tagName))) return false
  return !document.querySelector('[role="dialog"]')
}

/** Горячая клавиша на всю страницу (key — значение KeyboardEvent.key, например «/» или «?»); см. canUseHotkey */
export function useHotkey(key: string, handler: () => void) {
  const latest = useRef(handler)
  latest.current = handler

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== key || !canUseHotkey(e)) return
      e.preventDefault()
      latest.current()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [key])
}
