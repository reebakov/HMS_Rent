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
