import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { Route, Routes } from 'react-router-dom'
import { LoginPage } from './LoginPage'
import { api } from '@/lib/api'
import { makeSession, renderWithProviders } from '@/test/helpers'
import type { Session } from '@/lib/types'

let session: Session | null

vi.mock('@/auth/AuthProvider', () => ({ useAuth: () => ({ session, loading: false, login: vi.fn(), logout: vi.fn() }) }))
vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: (p: string) => `/api/v1${p}` },
}))

const renderLogin = () =>
  renderWithProviders(
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={<h1>главная</h1>} />
    </Routes>,
    { route: '/login' },
  )

beforeEach(() => {
  session = null
  vi.mocked(api.get).mockReset()
  vi.mocked(api.get).mockResolvedValue({ app_name: 'HMS Rent', bouncer_enabled: true, local_enabled: true, dev_enabled: false })
})

describe('LoginPage', () => {
  it('без сессии показывает страницу входа', async () => {
    renderLogin()
    expect(await screen.findByRole('link', { name: 'Корпоративный вход' })).toBeInTheDocument()
    expect(screen.queryByText('главная')).not.toBeInTheDocument()
  })

  it('уже вошедший пользователь уходит на главную, форму входа не видит', async () => {
    session = makeSession()
    renderLogin()
    expect(await screen.findByText('главная')).toBeInTheDocument()
  })
})
