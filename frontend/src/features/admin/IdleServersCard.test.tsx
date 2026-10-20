import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { IdleServersCard } from './IdleServersCard'
import { api } from '@/lib/api'
import { failGetOnce, renderWithProviders } from '@/test/helpers'
import type { IdleServers } from '@/lib/types'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))

const idle = (over: Partial<IdleServers> = {}): IdleServers => ({
  count: 3,
  average_days: 14,
  items: [
    { id: 1, name: 'A65', idle_days: 30, idle_since: '2026-09-20' },
    { id: 2, name: 'A32', idle_days: 1, idle_since: '2026-10-19' },
  ],
  ...over,
})

beforeEach(() => vi.mocked(api.get).mockReset())

describe('IdleServersCard', () => {
  it('показывает число свободных, среднее и самых долго простаивающих со склонением дней', async () => {
    vi.mocked(api.get).mockResolvedValue(idle())
    renderWithProviders(<IdleServersCard />)
    expect(await screen.findByText('Свободно: 3 · в среднем без выдачи 14 дней')).toBeInTheDocument()
    expect(screen.getByText('A65')).toBeInTheDocument()
    expect(screen.getByText('30 дней')).toBeInTheDocument()
    expect(screen.getByText('1 день')).toBeInTheDocument()
    expect(api.get).toHaveBeenCalledWith('/admin/idle')
  })

  it('нет свободных серверов — пояснение вместо пустого списка', async () => {
    vi.mocked(api.get).mockResolvedValue(idle({ count: 0, average_days: 0, items: [] }))
    renderWithProviders(<IdleServersCard />)
    expect(await screen.findByText('Свободных серверов в пулах нет')).toBeInTheDocument()
  })

  it('ошибка загрузки не выглядит пустым списком; «Повторить» перезапрашивает', async () => {
    const user = userEvent.setup()
    failGetOnce(vi.mocked(api.get), '/admin/idle')
    renderWithProviders(<IdleServersCard />)
    expect(await screen.findByText('Не удалось загрузить простой серверов')).toBeInTheDocument()
    expect(screen.queryByText('Свободных серверов в пулах нет')).not.toBeInTheDocument()
    vi.mocked(api.get).mockResolvedValue(idle())
    await user.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByText('A65')).toBeInTheDocument()
  })
})
