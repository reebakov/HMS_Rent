import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { useDebouncedSearch, useHotkey } from './hooks'

describe('useDebouncedSearch', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  const setup = (search: string, applied?: string) => {
    const apply = vi.fn()
    const hook = renderHook((p: { search: string; applied?: string }) => useDebouncedSearch(p.search, p.applied, apply), {
      initialProps: { search, applied },
    })
    return { apply, ...hook }
  }
  const wait = (ms: number) => act(() => void vi.advanceTimersByTime(ms))

  it('после монтирования без ввода ничего не применяет', () => {
    const { apply } = setup('')
    wait(1000)
    expect(apply).not.toHaveBeenCalled()
  })

  it('применяет введённое значение без пробелов, но только после паузы в 250 мс', () => {
    const { apply, rerender } = setup('')
    rerender({ search: '  pc-7 ', applied: undefined })
    wait(249)
    expect(apply).not.toHaveBeenCalled()
    wait(1)
    expect(apply).toHaveBeenCalledTimes(1)
    expect(apply).toHaveBeenCalledWith('pc-7')
  })

  it('быстрые правки не применяют промежуточные значения', () => {
    const { apply, rerender } = setup('')
    for (const s of ['p', 'pc', 'pc-']) {
      rerender({ search: s, applied: undefined })
      wait(100)
    }
    wait(250)
    expect(apply).toHaveBeenCalledTimes(1)
    expect(apply).toHaveBeenCalledWith('pc-')
  })

  it('значение, равное уже применённому (в том числе после обрезки пробелов), не применяется', () => {
    const { apply, rerender } = setup('pc', 'pc')
    wait(300)
    rerender({ search: ' pc ', applied: 'pc' })
    wait(300)
    expect(apply).not.toHaveBeenCalled()
  })

  it('очистка поля применяет undefined, если раньше было применено значение', () => {
    const { apply, rerender } = setup('pc', 'pc')
    rerender({ search: '   ', applied: 'pc' })
    wait(250)
    expect(apply).toHaveBeenCalledTimes(1)
    expect(apply).toHaveBeenCalledWith(undefined)
  })

  it('сверяет с актуальным применённым значением, а не с тем, что было при вводе', () => {
    const { apply, rerender } = setup('')
    rerender({ search: 'pc', applied: undefined })
    rerender({ search: 'pc', applied: 'pc' }) // поиск уже применён другим путём (например, из адреса)
    wait(250)
    expect(apply).not.toHaveBeenCalled()
  })
})

describe('useHotkey', () => {
  const press = (key: string, init: KeyboardEventInit = {}, target: Element = document.body) =>
    target.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init }))

  const setup = () => {
    const handler = vi.fn()
    const hook = renderHook(() => useHotkey('/', handler))
    return { handler, ...hook }
  }

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('вызывает обработчик по своей клавише и гасит действие браузера', () => {
    const { handler } = setup()
    expect(press('/')).toBe(false) // preventDefault вызван
    expect(handler).toHaveBeenCalledOnce()
  })

  it('чужую клавишу и сочетания с Ctrl/Alt/⌘ игнорирует', () => {
    const { handler } = setup()
    press('a')
    press('/', { ctrlKey: true })
    press('/', { altKey: true })
    press('/', { metaKey: true })
    expect(handler).not.toHaveBeenCalled()
  })

  it.each(['input', 'select', 'textarea'])('не срабатывает, пока фокус в <%s>', (tag) => {
    const { handler } = setup()
    const field = document.body.appendChild(document.createElement(tag))
    press('/', {}, field)
    expect(handler).not.toHaveBeenCalled()
  })

  it('не срабатывает при открытом окне', () => {
    const { handler } = setup()
    const dialog = document.body.appendChild(document.createElement('div'))
    dialog.setAttribute('role', 'dialog')
    press('/')
    expect(handler).not.toHaveBeenCalled()
  })

  it('после размонтирования обработчик снят', () => {
    const { handler, unmount } = setup()
    unmount()
    press('/')
    expect(handler).not.toHaveBeenCalled()
  })

  it('клавиша «?» (Shift+/) работает как отдельная', () => {
    const handler = vi.fn()
    renderHook(() => useHotkey('?', handler))
    press('?', { shiftKey: true })
    expect(handler).toHaveBeenCalledOnce()
  })
})
