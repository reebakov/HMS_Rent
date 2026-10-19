import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { LoginPage } from './LoginPage'
import { api } from '@/lib/api'
import { failGetOnce, makeSession, renderWithProviders } from '@/test/helpers'
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

  it('ошибка /auth/config: сообщение и «Повторить» вместо пустой формы; повтор показывает вход', async () => {
    const user = userEvent.setup()
    failGetOnce(vi.mocked(api.get), '/auth/config')
    renderLogin()
    expect(await screen.findByText('Не удалось загрузить настройки входа')).toBeInTheDocument()
    expect(screen.getByText('Сервер недоступен')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Корпоративный вход' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByRole('link', { name: 'Корпоративный вход' })).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('без корпоративного входа форма логина открыта сразу, с корпоративным — под раскрывающимся блоком', async () => {
    vi.mocked(api.get).mockResolvedValue({ app_name: 'HMS Rent', bouncer_enabled: false, local_enabled: false, dev_enabled: true })
    const { unmount } = renderLogin()
    expect(await screen.findByLabelText('Логин')).toBeInTheDocument()
    unmount()

    vi.mocked(api.get).mockResolvedValue({ app_name: 'HMS Rent', bouncer_enabled: true, local_enabled: true, dev_enabled: false })
    renderLogin()
    await userEvent.click(await screen.findByRole('button', { name: /Вход для администраторов/ }))
    expect(screen.getByLabelText('Логин')).toBeInTheDocument()
  })
})
