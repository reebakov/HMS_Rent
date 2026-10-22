import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { markProblemsSeen, useSeenProblemId } from './seen-problems'

const KEY = 'hmsrent:problems-seen'

beforeEach(() => localStorage.clear())

describe('seen-problems', () => {
  it('по умолчанию ничего не просмотрено', () => {
    expect(renderHook(() => useSeenProblemId()).result.current).toBe(0)
  })

  it('читает сохранённое значение; мусор считается нулём', () => {
    localStorage.setItem(KEY, '7')
    expect(renderHook(() => useSeenProblemId()).result.current).toBe(7)
    localStorage.setItem(KEY, 'abc')
    expect(renderHook(() => useSeenProblemId()).result.current).toBe(0)
  })

  it('markProblemsSeen обновляет подписчиков и запоминает в браузере', () => {
    const { result } = renderHook(() => useSeenProblemId())
    act(() => markProblemsSeen(5))
    expect(result.current).toBe(5)
    expect(localStorage.getItem(KEY)).toBe('5')
  })

  it('меньшее или равное число прежнее не затирает и подписчиков не будит', () => {
    localStorage.setItem(KEY, '8')
    const set = vi.spyOn(Storage.prototype, 'setItem')
    const { result } = renderHook(() => useSeenProblemId())
    act(() => markProblemsSeen(3))
    act(() => markProblemsSeen(8))
    expect(result.current).toBe(8)
    expect(set).not.toHaveBeenCalled()
    set.mockRestore()
  })

  it('без доступа к localStorage не падает', () => {
    const get = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied')
    })
    expect(renderHook(() => useSeenProblemId()).result.current).toBe(0)
    get.mockRestore()
  })
})
