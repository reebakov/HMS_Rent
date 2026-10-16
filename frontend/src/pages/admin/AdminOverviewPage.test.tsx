import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { AdminOverviewPage } from './AdminOverviewPage'
import { api } from '@/lib/api'
import { renderWithProviders } from '@/test/helpers'
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
    throw new Error(`неожиданный GET ${path}`)
  })
})

describe('AdminOverviewPage', () => {
  it('показывает сводку по парку', async () => {
    renderWithProviders(<AdminOverviewPage />)
    expect(await screen.findByText('Всего в учёте')).toBeInTheDocument()
    expect(screen.getByText('в пулах выдачи: 9')).toBeInTheDocument()
  })

  it('последние события запрашиваются с limit=10 (а не 50 по умолчанию бэкенда)', async () => {
    renderWithProviders(<AdminOverviewPage />)
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/admin/events', { limit: 10, offset: 0 }))
  })
})
