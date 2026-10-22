import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { ExecutorOrdersPage } from './ExecutorOrdersPage'
import { api } from '@/lib/api'
import { failGetOnce, makeExecutorOrder, renderWithProviders } from '@/test/helpers'
import type { ExecutorOrder } from '@/lib/types'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))

let orders: ExecutorOrder[]

const mount = () =>
  renderWithProviders(
    <Routes>
      <Route path="/executor" element={<ExecutorOrdersPage />} />
      <Route path="/executor/orders/:id" element={<p>страница-заказа</p>} />
    </Routes>,
    { route: '/executor' },
  )

beforeEach(() => {
  orders = [
    makeExecutorOrder(),
    makeExecutorOrder({ id: 8, order_number: 1043, computer: { ...makeExecutorOrder().computer, name: 'A065' }, prepared_at: '2026-10-21T10:00:00Z' }),
  ]
  vi.mocked(api.get).mockReset()
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/executor/orders') return orders
    throw new Error(`неожиданный GET ${path}`)
  })
})

describe('ExecutorOrdersPage', () => {
  it('показывает заказы со статусом подготовки и число ждущих', async () => {
    mount()
    const waiting = (await screen.findByRole('link', { name: 'A032' })).closest('tr')!
    expect(within(waiting).getByText('Ждёт подготовки')).toBeInTheDocument()
    expect(within(waiting).getByText('Windows 11 26H2')).toBeInTheDocument()
    expect(within(waiting).getByText('Пётр Петров (petrov)')).toBeInTheDocument()
    const done = screen.getByRole('link', { name: 'A065' }).closest('tr')!
    expect(within(done).getByText('Подготовлен')).toBeInTheDocument()
    expect(screen.getByText('Ждут подготовки: 1 заказ')).toBeInTheDocument()
  })

  it('в очереди у каждого заказа ссылка на его заявку в Jira', async () => {
    orders[0] = makeExecutorOrder({ request_key: 'HMS-77', request_url: 'https://jira.test/browse/HMS-77', request_status: 'Ожидает поддержки' })
    mount()
    const row = (await screen.findByRole('link', { name: 'A032' })).closest('tr')!
    expect(within(row).getByRole('link', { name: 'HMS-77' })).toHaveAttribute('href', 'https://jira.test/browse/HMS-77')
    expect(within(row).getByText('· Ожидает поддержки')).toBeInTheDocument()
    const other = screen.getByRole('link', { name: 'A065' }).closest('tr')!
    expect(within(other).getByText('Заявки нет')).toBeInTheDocument()
  })

  it('ссылка ПК ведёт на страницу заказа', async () => {
    mount()
    await userEvent.click(await screen.findByRole('link', { name: 'A032' }))
    expect(screen.getByText('страница-заказа')).toBeInTheDocument()
  })

  it('все подготовлены — об этом сказано в заголовке', async () => {
    orders = [makeExecutorOrder({ prepared_at: '2026-10-21T10:00:00Z' })]
    mount()
    expect(await screen.findByText('Все выданные ПК подготовлены')).toBeInTheDocument()
  })

  it('пустая очередь — понятная заглушка', async () => {
    orders = []
    mount()
    expect(await screen.findByText('Выданных ПК нет')).toBeInTheDocument()
  })

  it('ошибка загрузки не выглядит как пустой список: «Повторить» загружает снова', async () => {
    failGetOnce(vi.mocked(api.get), '/executor/orders')
    mount()
    expect(await screen.findByText('Не удалось загрузить заказы')).toBeInTheDocument()
    expect(screen.queryByText('Выданных ПК нет')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByRole('link', { name: 'A032' })).toBeInTheDocument()
  })
})
