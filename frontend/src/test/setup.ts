import '@testing-library/jest-dom/vitest'
import { cleanup, configure } from '@testing-library/react'
import { afterEach } from 'vitest'

// файлы тестов идут параллельно и делят CPU: стандартной 1 с на waitFor/findBy иногда не хватает
configure({ asyncUtilTimeout: 10_000 })

afterEach(() => {
  cleanup()
  localStorage.clear()
})

// jsdom не реализует часть API, которые нужны Radix UI
if (!window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false,
    }) as MediaQueryList
}
window.HTMLElement.prototype.scrollIntoView ??= () => undefined
window.HTMLElement.prototype.hasPointerCapture ??= () => false
window.HTMLElement.prototype.releasePointerCapture ??= () => undefined
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
}
