import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Pagination } from './pagination'

const setup = (page: number, total = 750, onChange = vi.fn()) => {
  render(<Pagination page={page} pageSize={100} total={total} onChange={onChange} />)
  return onChange
}
const numbers = () =>
  screen
    .getAllByRole('button')
    .map((b) => b.textContent)
    .filter((t) => /^\d+$/.test(t ?? ''))

describe('Pagination', () => {
  it('без записей — «0 записей» и без кнопок', () => {
    setup(0, 0)
    expect(screen.getByText('0 записей')).toBeInTheDocument()
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument()
  })

  it('показывает диапазон записей и скользящее окно из пяти страниц', () => {
    setup(0)
    expect(screen.getByText('1–100 из 750')).toBeInTheDocument()
    expect(numbers()).toEqual(['1', '2', '3', '4', '5'])
  })

  it.each([
    [3, ['2', '3', '4', '5', '6']],
    [7, ['4', '5', '6', '7', '8']],
  ])('окно вокруг страницы %i', (page, expected) => {
    setup(page)
    expect(numbers()).toEqual(expected)
  })

  it('последняя страница неполная: диапазон обрезается по total', () => {
    setup(7)
    expect(screen.getByText('701–750 из 750')).toBeInTheDocument()
  })

  it('навигация подписана; на первой странице «назад» и «в начало» недоступны', () => {
    setup(0)
    const nav = screen.getByRole('navigation', { name: 'Страницы' })
    expect(nav).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'На первую страницу' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Предыдущая страница' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Следующая страница' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'На последнюю страницу' })).toBeEnabled()
    expect(screen.getByTitle('На последнюю страницу')).toBe(screen.getByRole('button', { name: 'На последнюю страницу' }))
  })

  it('на последней странице «вперёд» и «в конец» недоступны', () => {
    setup(7)
    expect(screen.getByRole('button', { name: 'Следующая страница' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'На последнюю страницу' })).toBeDisabled()
  })

  it('текущая страница помечена aria-current="page", остальные — нет', () => {
    setup(2)
    expect(screen.getByRole('button', { name: '3' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('button', { name: '2' })).not.toHaveAttribute('aria-current')
  })

  it('кнопки вызывают onChange с номером страницы (с нуля)', async () => {
    const user = userEvent.setup()
    const onChange = setup(3)
    await user.click(screen.getByRole('button', { name: 'Следующая страница' }))
    await user.click(screen.getByRole('button', { name: 'Предыдущая страница' }))
    await user.click(screen.getByRole('button', { name: 'На первую страницу' }))
    await user.click(screen.getByRole('button', { name: 'На последнюю страницу' }))
    await user.click(screen.getByRole('button', { name: '5' }))
    expect(onChange.mock.calls.map(([p]) => p)).toEqual([4, 2, 0, 7, 4])
  })
})
