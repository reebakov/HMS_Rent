import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, renderHook, screen, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { safeStorage } from './storage'
import { ThemeToggle } from '@/components/layout/ThemeToggle'
import { useViewMode } from '@/components/ui/view-toggle'

/** Браузер без доступа к хранилищу (приватное окно, запрет сайт-данных): любое обращение бросает исключение */
const blockStorage = () => {
  const boom = () => {
    throw new DOMException('denied', 'SecurityError')
  }
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(boom)
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(boom)
}

afterEach(() => document.documentElement.classList.remove('dark'))

describe('safeStorage', () => {
  it('читает и пишет как обычный localStorage', () => {
    safeStorage.set('k', 'v')
    expect(safeStorage.get('k')).toBe('v')
    expect(safeStorage.get('нет такого')).toBeNull()
  })

  it('при недоступном хранилище get даёт null, set молча ничего не делает', () => {
    blockStorage()
    expect(safeStorage.get('k')).toBeNull()
    expect(() => safeStorage.set('k', 'v')).not.toThrow()
  })
})

describe('компоненты при недоступном localStorage', () => {
  it('ThemeToggle переключает тему и не падает', async () => {
    blockStorage()
    const user = userEvent.setup()
    render(<ThemeToggle />)
    await user.click(screen.getByRole('button'))
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })

  it('useViewMode работает со значением по умолчанию и переключается', () => {
    blockStorage()
    const { result } = renderHook(() => useViewMode('catalog'))
    expect(result.current[0]).toBe('cards')
    act(() => result.current[1]('compact'))
    expect(result.current[0]).toBe('compact')
  })
})
