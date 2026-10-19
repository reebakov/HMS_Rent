import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { useDebouncedSearch } from './hooks'

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
