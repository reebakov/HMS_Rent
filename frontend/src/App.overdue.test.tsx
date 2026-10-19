import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import App from './App'
import { AuthProvider } from '@/auth/AuthProvider'
import { api } from '@/lib/api'
import { makeSession, renderWithProviders } from '@/test/helpers'
import type { Session } from '@/lib/types'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))
// как в App.test.tsx: страницы — заглушки, проверяем только маршрут и гард
vi.mock('@/pages/CatalogPage', () => ({ CatalogPage: () => <h1>stub:catalog</h1> }))
vi.mock('@/pages/admin/OverduePage', () => ({ OverduePage: () => <h1>stub:admin-overdue</h1> }))

function mount(route: string, session: Session) {
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/auth/me') return session
    if (path === '/admin/overdue') return []
    throw new Error(`неожиданный GET ${path}`)
  })
  return renderWithProviders(<AuthProvider><App /></AuthProvider>, { route })
}

beforeEach(() => {
  vi.mocked(api.get).mockReset()
})

describe('маршрут /admin/overdue', () => {
  it('админ попадает на страницу просрочек внутри AppShell', async () => {
    mount('/admin/overdue', makeSession({ role: 'admin' }))
    expect(await screen.findByText('stub:admin-overdue')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /^Просрочки/ })).toHaveAttribute('aria-current', 'page')
  })

  it('сотрудника гард отправляет в каталог', async () => {
    mount('/admin/overdue', makeSession())
    expect(await screen.findByText('stub:catalog')).toBeInTheDocument()
    expect(screen.queryByText('stub:admin-overdue')).not.toBeInTheDocument()
  })
})
