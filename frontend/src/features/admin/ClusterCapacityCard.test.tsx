import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ClusterCapacityCard } from './ClusterCapacityCard'
import { api } from '@/lib/api'
import { failGetOnce, renderWithProviders } from '@/test/helpers'
import type { ClusterCapacity } from '@/lib/types'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))

const capacity = (over: Partial<ClusterCapacity> = {}): ClusterCapacity => ({
  ok: true,
  error: null,
  cpu_total_ghz: 420,
  cpu_free_ghz: 320,
  ram_total_gb: 1200,
  ram_free_gb: 540,
  storage_total_gb: 25000,
  storage_free_gb: 15500,
  ...over,
})

beforeEach(() => vi.mocked(api.get).mockReset())

describe('ClusterCapacityCard', () => {
  it('показывает свободное и общее по процессору, памяти и хранилищу, шкала — доля занятого', async () => {
    vi.mocked(api.get).mockResolvedValue(capacity())
    renderWithProviders(<ClusterCapacityCard />)
    expect(await screen.findByText('свободно 320 из 420 ГГц')).toBeInTheDocument()
    expect(screen.getByText('свободно 540 из 1200 ГБ')).toBeInTheDocument()
    expect(screen.getByText('свободно 15500 из 25000 ГБ')).toBeInTheDocument()
    expect(screen.getByRole('meter', { name: 'Память: занято' })).toHaveAttribute('aria-valuenow', '55')
    expect(screen.getByRole('meter', { name: 'Процессор: занято' })).toHaveAttribute('aria-valuenow', '24')
    expect(api.get).toHaveBeenCalledWith('/admin/cluster')
  })

  it('vCenter не подключён или ответил ошибкой — причина вместо шкал', async () => {
    vi.mocked(api.get).mockResolvedValue(capacity({ ok: false, error: 'vCenter не подключён' }))
    renderWithProviders(<ClusterCapacityCard />)
    expect(await screen.findByText('vCenter не подключён')).toBeInTheDocument()
    expect(screen.queryByRole('meter')).not.toBeInTheDocument()
  })

  it('нулевой объём не даёт деления на ноль', async () => {
    vi.mocked(api.get).mockResolvedValue(capacity({ cpu_total_ghz: 0, cpu_free_ghz: 0 }))
    renderWithProviders(<ClusterCapacityCard />)
    expect(await screen.findByRole('meter', { name: 'Процессор: занято' })).toHaveAttribute('aria-valuenow', '0')
  })

  it('ошибка запроса: сообщение и «Повторить», перезапрос показывает данные', async () => {
    const user = userEvent.setup()
    failGetOnce(vi.mocked(api.get), '/admin/cluster')
    renderWithProviders(<ClusterCapacityCard />)
    expect(await screen.findByText('Не удалось загрузить мощности кластера')).toBeInTheDocument()
    vi.mocked(api.get).mockResolvedValue(capacity())
    await user.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByText('свободно 540 из 1200 ГБ')).toBeInTheDocument()
  })
})
