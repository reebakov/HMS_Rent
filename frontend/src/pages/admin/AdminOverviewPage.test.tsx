import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AdminOverviewPage } from './AdminOverviewPage'
import { api } from '@/lib/api'
import { failGetOnce, renderWithProviders } from '@/test/helpers'
import type { Stats } from '@/lib/types'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))

const stats: Stats = {
  total: 12,
  by_status: { available: 5, booked: 4, maintenance: 1, in_use: 1, retired: 1 },
  by_tier: [],
  in_pools: 9,
  active_bookings: 4,
  departments_using: 2,
  overdue: 0,
  issues: 0,
  last_sync: null,
}

beforeEach(() => {
  vi.mocked(api.get).mockReset()
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/admin/stats') return stats
    if (path === '/admin/departments') return []
    if (path === '/admin/events') return { items: [], total: 0 }
    if (path === '/admin/idle') return { count: 0, average_days: 0, items: [] }
    if (path === '/admin/cluster') return { ok: false, error: 'vCenter не подключён', cpu_total_ghz: 0, cpu_free_ghz: 0, ram_total_gb: 0, ram_free_gb: 0, storage_total_gb: 0, storage_free_gb: 0 }
    throw new Error(`неожиданный GET ${path}`)
  })
})

describe('AdminOverviewPage', () => {
  it('под сводкой — простой серверов и мощности кластера', async () => {
    renderWithProviders(<AdminOverviewPage />)
    expect(await screen.findByText('Простой серверов')).toBeInTheDocument()
    expect(await screen.findByText('Мощности кластера')).toBeInTheDocument()
    expect(await screen.findByText('vCenter не подключён')).toBeInTheDocument()
  })

  it('показывает сводку по парку', async () => {
    renderWithProviders(<AdminOverviewPage />)
    expect(await screen.findByText('Всего в учёте')).toBeInTheDocument()
    expect(screen.getByText('в пулах выдачи: 9')).toBeInTheDocument()
  })

  it('последние события запрашиваются с limit=10 (а не 50 по умолчанию бэкенда)', async () => {
    renderWithProviders(<AdminOverviewPage />)
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/admin/events', { limit: 10, offset: 0 }))
  })

  it('ошибка сводки: «Повторить» в каждом блоке сводки, скелетон не висит, повтор перезапрашивает', async () => {
    const user = userEvent.setup()
    failGetOnce(vi.mocked(api.get), '/admin/stats')
    const { container } = renderWithProviders(<AdminOverviewPage />)
    await waitFor(() => expect(screen.getAllByText('Не удалось загрузить сводку')).toHaveLength(3))
    expect(screen.getAllByText('Сервер недоступен')).toHaveLength(3)
    expect(screen.queryByText('Всего в учёте')).not.toBeInTheDocument()
    expect(screen.queryByText('Синхронизаций ещё не было')).not.toBeInTheDocument()
    expect(container.querySelector('.animate-pulse')).toBeNull()

    await user.click(screen.getAllByRole('button', { name: 'Повторить' })[0])
    expect(await screen.findByText('Всего в учёте')).toBeInTheDocument()
    expect(screen.queryByText('Не удалось загрузить сводку')).not.toBeInTheDocument()
  })

  it('ошибка отделов: сообщение вместо «Пока ни один ПК не закреплён»; повтор перезапрашивает', async () => {
    const user = userEvent.setup()
    failGetOnce(vi.mocked(api.get), '/admin/departments')
    renderWithProviders(<AdminOverviewPage />)
    expect(await screen.findByText('Не удалось загрузить отделы')).toBeInTheDocument()
    expect(screen.queryByText('Пока ни один ПК не закреплён')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByText('Пока ни один ПК не закреплён')).toBeInTheDocument()
  })

  it('ошибка событий: сообщение вместо «Событий пока нет»; повтор перезапрашивает', async () => {
    const user = userEvent.setup()
    failGetOnce(vi.mocked(api.get), '/admin/events')
    renderWithProviders(<AdminOverviewPage />)
    const alert = await screen.findByRole('alert')
    expect(within(alert).getByText('Не удалось загрузить события')).toBeInTheDocument()
    expect(screen.queryByText('Событий пока нет')).not.toBeInTheDocument()

    await user.click(within(alert).getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByText('Событий пока нет')).toBeInTheDocument()
  })
})
